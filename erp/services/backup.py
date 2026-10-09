"""Banco de dados guardado no FTP (e/ou S3): backup verificado, histórico de versões e restauração.

O SQLite trabalha no disco do servidor do app; após cada alteração uma cópia é enviada para
``<diretório base>/backup-banco/`` junto com um manifesto (``latest.json``) e conferida por SHA-256
(baixada de volta e comparada). Quando o app inicia com o banco vazio, a última versão é restaurada.

Proteção contra sobrescrita: o envio automático só fica "armado" depois que o app sabe que a versão
remota é a mesma do banco local (restaurou dela, ou não havia backup remoto, ou o admin confirmou).
Assim um banco recém-criado em branco nunca apaga o backup bom do FTP.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from erp import db
from erp.config import db_path
from erp.storage import DualStorage

REMOTE_DIR = "backup-banco"
LATEST_KEY = f"{REMOTE_DIR}/erp_obra_latest.db"
MANIFEST_KEY = f"{REMOTE_DIR}/latest.json"
SQLITE_HEADER = b"SQLite format 3\x00"
AUTO_INTERVAL_S = 120
ERP_TABLES = {"users", "settings", "tasks", "wbs"}

_lock = threading.Lock()
_state: dict = {"last_check": 0.0, "last_hash": None, "last_ok": None, "last_error": None,
                "armed": False, "startup": None}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- banco local
def snapshot() -> bytes:
    """Cópia consistente do banco (API de backup do SQLite, segura com WAL)."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "snap.db"
        src, dst = db.connect(), sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return target.read_bytes()


def describe(data: bytes) -> dict:
    """Resumo de um arquivo de banco: obra, nº de registros e data da última movimentação."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "d.db"
        p.write_bytes(data)
        conn = sqlite3.connect(p)
        try:
            def one(sql: str):
                try:
                    return conn.execute(sql).fetchone()[0]
                except sqlite3.Error:
                    return None
            return {
                "project": one("SELECT value FROM settings WHERE key = 'project_name'") or "-",
                "tasks": one("SELECT COUNT(*) FROM tasks") or 0,
                "rdos": one("SELECT COUNT(*) FROM rdo") or 0,
                "invoices": one("SELECT COUNT(*) FROM invoices") or 0,
                "last_rdo": one("SELECT MAX(date) FROM rdo"),
                "size": len(data),
                "sha256": _sha(data),
            }
        finally:
            conn.close()


def validate(data: bytes) -> str | None:
    """Retorna mensagem de erro ou None se o arquivo for um backup válido do ERP."""
    if not data.startswith(SQLITE_HEADER):
        return "O arquivo não é um banco SQLite."
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "check.db"
        p.write_bytes(data)
        conn = sqlite3.connect(p)
        try:
            if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                return "Banco corrompido (falha na verificação de integridade)."
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if not ERP_TABLES <= tables:
                return "O banco não tem as tabelas do ERP Obras."
            if not conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                return "O backup não tem nenhum usuário."
        except sqlite3.DatabaseError as exc:
            return f"Banco corrompido: {exc}"
        finally:
            conn.close()
    return None


def restore(data: bytes, origin: str = "arquivo enviado", version: str | None = None) -> dict:
    """Substitui todo o conteúdo do banco atual pelo backup e registra qual versão foi restaurada."""
    error = validate(data)
    if error:
        raise ValueError(error)
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "restore.db"
        p.write_bytes(data)
        src, dst = sqlite3.connect(p), db.connect()
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
    db.init_db()  # aplica tabelas novas do schema, se o backup for de versão anterior
    info = {**describe(data), "origin": origin, "version": version or "-",
            "restored_at": datetime.now().isoformat(timespec="seconds")}
    db.set_setting("backup_last_restore", json.dumps(info, ensure_ascii=False))
    _state["last_hash"] = _sha(snapshot())  # o registro acima já mudou o banco; evita reenvio inútil
    return info


def known_versions() -> set[str]:
    """Versões remotas das quais o banco local descende (último envio ou última restauração)."""
    out = set()
    for key in ("backup_last_push", "backup_last_restore"):
        raw = db.get_setting(key)
        if raw:
            out.add(json.loads(raw).get("version"))
    out.discard(None)
    out.discard("-")
    return out


def last_restore() -> dict | None:
    raw = db.get_setting("backup_last_restore")
    return json.loads(raw) if raw else None


def backup_filename(now: datetime | None = None) -> str:
    return f"erp_obra_{(now or datetime.now()):%Y%m%d_%H%M%S}.db"


# --------------------------------------------------------------------------- remoto (FTP/S3)
def _backends(storage: DualStorage) -> list:
    """FTP primeiro (fonte principal do banco), depois S3."""
    return [b for b in (storage.ftp, storage.s3) if b.configured]


def remote_configured(storage: DualStorage | None = None) -> bool:
    return bool(_backends(storage or DualStorage()))


def remote_manifest(storage: DualStorage | None = None) -> dict | None:
    """Manifesto da última versão no servidor (None se não houver backup remoto)."""
    for backend in _backends(storage or DualStorage()):
        try:
            return json.loads(backend.download(MANIFEST_KEY).decode("utf-8"))
        except Exception:  # noqa: BLE001
            continue
    return None


def push_remote(data: bytes | None = None, storage: DualStorage | None = None, *, force: bool = False,
                verify: bool = True) -> dict:
    """Envia o banco: latest.db + cópia datada + latest.json; confere baixando de volta (SHA-256).

    Sem ``force``, recusa sobrescrever uma versão remota diferente enquanto o envio não estiver armado.
    """
    storage = storage or DualStorage()
    backends = _backends(storage)
    if not backends:
        return {"ok": False, "message": "FTP/S3 não configurados."}
    if not force and not _state["armed"]:
        remote = remote_manifest(storage)
        if remote and remote.get("version") not in known_versions():
            return {"ok": False, "blocked": True, "remote": remote,
                    "message": "Envio bloqueado: o servidor tem uma versão diferente do banco local. "
                               "Restaure-a ou confirme a substituição."}
    data = data if data is not None else snapshot()
    now = datetime.now()
    version = backup_filename(now)
    manifest = {**describe(data), "version": version, "key": f"{REMOTE_DIR}/{now:%Y/%m}/{version}",
                "created_at": now.isoformat(timespec="seconds")}
    results, errors = {}, []
    for backend in backends:
        name = "ftp" if backend is storage.ftp else "s3"
        try:
            backend.upload(manifest["key"], data)
            backend.upload(LATEST_KEY, data)
            if verify and _sha(backend.download(LATEST_KEY)) != manifest["sha256"]:
                raise OSError("arquivo conferido difere do enviado")
            backend.upload(MANIFEST_KEY, json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"))
            results[name] = "ok"
        except Exception as exc:  # noqa: BLE001
            results[name] = "erro"
            errors.append(f"{name.upper()}: {exc}")
    ok = "ok" in results.values()
    if ok:
        _state.update(last_ok=now, last_hash=manifest["sha256"], armed=True, last_manifest=manifest)
        db.set_setting("backup_last_push", json.dumps({**manifest, **results}, ensure_ascii=False))
        _state["last_hash"] = _sha(snapshot())  # a linha acima alterou o banco
    _state["last_error"] = "; ".join(errors) or None
    msg = (f"Backup {version} enviado e conferido (SHA-256) em: "
           + ", ".join(k.upper() for k, v in results.items() if v == "ok")) if ok else "Falha no backup: " + "; ".join(errors)
    if ok and errors:
        msg += " | " + "; ".join(errors)
    return {"ok": ok, "message": msg, "manifest": manifest, "results": results, "errors": errors}


def list_versions(storage: DualStorage | None = None) -> list[str]:
    """Versões datadas disponíveis no servidor (mais recente primeiro)."""
    for backend in _backends(storage or DualStorage()):
        try:
            keys = [k for k in backend.list_files(REMOTE_DIR) if k.endswith(".db") and k != LATEST_KEY]
            return sorted(keys, key=lambda k: k.rsplit("/", 1)[-1], reverse=True)
        except Exception:  # noqa: BLE001
            continue
    return []


def fetch_remote(key: str = LATEST_KEY, storage: DualStorage | None = None) -> bytes | None:
    for backend in _backends(storage or DualStorage()):
        try:
            return backend.download(key)
        except Exception:  # noqa: BLE001
            continue
    return None


def restore_from_remote(key: str = LATEST_KEY, storage: DualStorage | None = None) -> dict:
    data = fetch_remote(key, storage)
    if data is None:
        raise ValueError(f"Não foi possível baixar {key} do servidor.")
    version = key.rsplit("/", 1)[-1]
    if key == LATEST_KEY:
        version = (remote_manifest(storage) or {}).get("version", version)
    info = restore(data, origin="servidor FTP/S3", version=version)
    _state["armed"] = key == LATEST_KEY  # restaurou a mais recente: pode voltar a enviar automaticamente
    return info


def restore_latest_remote(storage: DualStorage | None = None) -> bool:
    """Na inicialização com banco vazio: restaura a última versão remota e registra o resultado."""
    storage = storage or DualStorage()
    status = {"at": datetime.now().isoformat(timespec="seconds"), "configured": remote_configured(storage)}
    if not status["configured"]:
        status.update(ok=False, message="FTP/S3 não configurados: o app iniciou sem restaurar backup.")
        _state["startup"] = status
        return False
    try:
        manifest = remote_manifest(storage)
        data = fetch_remote(LATEST_KEY, storage)
        if data is None:
            # servidor acessível e sem backup? Só arma se o manifesto também não existe (1º uso).
            reachable = any(b.test()[0] for b in _backends(storage))
            status.update(ok=False, reachable=reachable,
                          message="Nenhum backup encontrado no servidor (primeiro uso)." if reachable
                          else "Servidor FTP/S3 inacessível: banco NÃO restaurado. Confira o endereço do FTP.")
            _state["armed"] = reachable and manifest is None
        else:
            info = restore(data, origin="servidor FTP/S3 (automático na inicialização)",
                           version=(manifest or {}).get("version"))
            _state["armed"] = True
            status.update(ok=True, message=f"Banco restaurado do servidor: versão {info['version']}.", info=info)
    except Exception as exc:  # noqa: BLE001
        status.update(ok=False, message=f"Falha ao restaurar do servidor: {exc}")
    _state["startup"] = status
    return bool(status.get("ok"))


def maybe_auto_backup(force: bool = False, background: bool = True) -> None:
    """Chamado a cada interação; envia o banco se mudou, no máximo a cada AUTO_INTERVAL_S segundos."""
    if not force and time.time() - _state["last_check"] < AUTO_INTERVAL_S:
        return
    _state["last_check"] = time.time()

    def job() -> None:
        if not _lock.acquire(blocking=False):
            return
        try:
            storage = DualStorage()
            if not _backends(storage):
                return
            data = snapshot()
            if _sha(data) != _state["last_hash"]:
                res = push_remote(data, storage)
                if res.get("blocked"):
                    _state["last_error"] = res["message"]
        except Exception as exc:  # noqa: BLE001
            _state["last_error"] = str(exc)
        finally:
            _lock.release()

    if background:
        threading.Thread(target=job, daemon=True).start()
    else:
        job()


def arm(value: bool = True) -> None:
    _state["armed"] = value


def status() -> dict:
    push = db.get_setting("backup_last_push")
    return {"last_ok": _state["last_ok"], "last_error": _state["last_error"], "armed": _state["armed"],
            "startup": _state["startup"], "last_push": json.loads(push) if push else None,
            "db_path": str(db_path())}
