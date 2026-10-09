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
                "armed": False, "startup": None, "problem": None, "pulled": None}


# --------------------------------------------------------------------------- problemas de conexão
def classify(text: str) -> str:
    """unreachable (endereço/porta/rede) · auth (usuário/senha) · write (sem permissão de gravação)."""
    t = (text or "").lower()
    if "530" in t or "login" in t or "authentication" in t or "senha" in t or "password" in t:
        return "auth"
    if "550" in t or "553" in t or "permission" in t or "permissão" in t:
        return "write"
    return "unreachable"


def _set_problem(kind: str, detail: str, startup: bool = False) -> None:
    current = _state["problem"]
    _state["problem"] = {
        "kind": kind, "detail": detail,
        "since": current["since"] if current and current["kind"] == kind else datetime.now(),
        "startup": startup or bool(current and current.get("startup")),
    }


def _clear_problem(include_startup: bool = True) -> None:
    if _state["problem"] and (include_startup or not _state["problem"].get("startup")):
        _state["problem"] = None


def connection_problem() -> dict | None:
    """Problema ativo com o servidor de backup (None se tudo certo)."""
    return _state["problem"]


def health_check(storage: DualStorage | None = None) -> bool:
    """Login no FTP/S3; registra ou limpa o problema de conexão."""
    backends = _backends(storage or DualStorage())
    if not backends:
        return False
    errors = []
    for backend in backends:
        ok, msg = backend.test()
        if ok:
            _clear_problem(include_startup=False)
            return True
        errors.append(msg)
    _set_problem(classify(errors[0]), "; ".join(errors))
    return False


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sync_file() -> Path:
    from erp.config import data_dir

    return data_dir() / "sync_state.json"


def _synced_hash() -> str | None:
    """SHA do banco local logo após o último envio/restauração (persistido entre reinícios)."""
    if _state["last_hash"] is None:
        try:
            _state["last_hash"] = json.loads(_sync_file().read_text(encoding="utf-8")).get("sha")
        except (OSError, ValueError):
            pass
    return _state["last_hash"]


def _mark_synced() -> None:
    _state["last_hash"] = _sha(snapshot())
    try:
        _sync_file().write_text(json.dumps({"sha": _state["last_hash"]}), encoding="utf-8")
    except OSError:
        pass


def local_changed() -> bool:
    return _sha(snapshot()) != _synced_hash()


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
    _mark_synced()  # o registro acima já mudou o banco; evita reenvio inútil
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
    now = now or datetime.now()
    return f"erp_obra_{now:%Y%m%d_%H%M%S}_{now.microsecond // 1000:03d}.db"


# --------------------------------------------------------------------------- remoto (FTP/S3)
def _backends(storage: DualStorage) -> list:
    """FTP primeiro (fonte principal do banco), depois S3. Nenhum no modo "disco local"."""
    if not storage.remote:
        return []
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
    if not force:  # nunca sobrescreve uma versão que este banco não conhece (outro computador/site, reinício)
        remote = remote_manifest(storage)
        if remote and remote.get("version") not in known_versions():
            _state["armed"] = False
            _set_problem("blocked", f"O servidor tem a versão {remote.get('version')}, diferente do banco local.")
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
        _clear_problem()
        _state.update(last_ok=now, last_hash=manifest["sha256"], armed=True, last_manifest=manifest)
        db.set_setting("backup_last_push", json.dumps({**manifest, **results}, ensure_ascii=False))
        _mark_synced()  # a linha acima alterou o banco
    _state["last_error"] = "; ".join(errors) or None
    if not ok:
        _set_problem(classify(errors[0]), "; ".join(errors))
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
    _clear_problem()
    _state["armed"] = True
    if key != LATEST_KEY:  # voltar a uma versão antiga = publicá-la como a mais recente (as outras ficam no histórico)
        push_remote(storage=storage, force=True)
    return info


def sync(storage: DualStorage | None = None) -> str:
    """Sincroniza com o servidor: 'pushed', 'pulled', 'conflict', 'unchanged' ou 'error'.

    - versão remota conhecida e banco local alterado -> envia;
    - versão remota desconhecida (gravada por outro computador/site) e banco local sem alterações -> baixa;
    - versão remota desconhecida e banco local alterado -> conflito: pausa e alerta o administrador.
    """
    storage = storage or DualStorage()
    if not _backends(storage):
        return "unchanged"
    try:
        remote = remote_manifest(storage)
    except Exception as exc:  # noqa: BLE001
        _set_problem(classify(str(exc)), str(exc))
        return "error"
    if remote is None and not any(b.test()[0] for b in _backends(storage)):
        health_check(storage)
        return "error"
    changed = local_changed()
    if remote and remote.get("version") not in known_versions():
        if changed:
            _state["armed"] = False
            _set_problem("blocked", f"O servidor tem a versão {remote.get('version')} (gravada em outro lugar) e "
                                    "este banco também tem lançamentos novos.")
            return "conflict"
        restore(fetch_remote(LATEST_KEY, storage) or b"", origin="servidor FTP/S3 (sincronização automática)",
                version=remote.get("version"))
        _clear_problem()
        _state["armed"] = True
        _state["pulled"] = datetime.now()
        return "pulled"
    _clear_problem(include_startup=False)
    if changed:
        return "pushed" if push_remote(storage=storage)["ok"] else "error"
    return "unchanged"


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
            if not reachable:
                detail = "; ".join(b.test()[1] for b in _backends(storage))
                _set_problem(classify(detail), detail, startup=True)
        else:
            info = restore(data, origin="servidor FTP/S3 (automático na inicialização)",
                           version=(manifest or {}).get("version"))
            _state["armed"] = True
            status.update(ok=True, message=f"Banco restaurado do servidor: versão {info['version']}.", info=info)
    except Exception as exc:  # noqa: BLE001
        status.update(ok=False, message=f"Falha ao restaurar do servidor: {exc}")
        _set_problem(classify(str(exc)), str(exc), startup=True)
    _state["startup"] = status
    return bool(status.get("ok"))


def maybe_auto_backup(force: bool = False, background: bool = True) -> None:
    """Chamado a cada interação; sincroniza com o FTP no máximo a cada AUTO_INTERVAL_S segundos."""
    if not force and time.time() - _state["last_check"] < AUTO_INTERVAL_S:
        return
    _state["last_check"] = time.time()

    def job() -> None:
        if not _lock.acquire(blocking=False):
            return
        try:
            if _state["problem"] and _state["problem"].get("startup"):
                return  # banco não restaurado no reinício: nada sincroniza até o admin restaurar
            sync()
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
            "problem": _state["problem"],
            "startup": _state["startup"], "last_push": json.loads(push) if push else None,
            "db_path": str(db_path())}
