"""Armazenamento duplo de mídias: AWS S3 (produção) + FTP privado (backup físico estruturado).

Toda mídia também é mantida em cache local (``data/media``) para que o app funcione
mesmo sem credenciais configuradas. Os envios para S3 e FTP rodam simultaneamente
em threads separadas.
"""
from __future__ import annotations

import ftplib
import io
import mimetypes
import posixpath
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from erp.config import media_dir
from erp.settings_store import load_connection_settings

NOT_CONFIGURED = "não configurado"
OK = "ok"


def safe_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or "arquivo"


def build_key(category: str, filename: str, when: datetime | None = None) -> str:
    """Estrutura física: categoria/AAAA/MM/uuid_nome."""
    when = when or datetime.now()
    cat = safe_filename(category.lower().replace("/", "-")) or "geral"
    return f"{cat}/{when:%Y}/{when:%m}/{uuid.uuid4().hex[:10]}_{safe_filename(filename)}"


@dataclass
class StorageResult:
    key: str
    size: int
    local: str = OK
    s3: str = NOT_CONFIGURED
    ftp: str = NOT_CONFIGURED
    errors: list[str] = field(default_factory=list)

    @property
    def remote_ok(self) -> bool:
        return self.s3 == OK or self.ftp == OK


class S3Backend:
    def __init__(self, settings: dict[str, str]):
        self.access_key = settings.get("AWS_ACCESS_KEY_ID", "")
        self.secret_key = settings.get("AWS_SECRET_ACCESS_KEY", "")
        self.region = settings.get("AWS_REGION") or "sa-east-1"
        self.bucket = settings.get("S3_BUCKET", "")
        self.prefix = (settings.get("S3_PREFIX") or "").strip("/")
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(self.access_key and self.secret_key and self.bucket)

    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "s3",
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
            )
        return self._client

    def _full_key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def upload(self, key: str, data: bytes, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self.client().put_object(Bucket=self.bucket, Key=self._full_key(key), Body=data, **extra)

    def download(self, key: str) -> bytes:
        obj = self.client().get_object(Bucket=self.bucket, Key=self._full_key(key))
        return obj["Body"].read()

    def list_files(self, prefix: str) -> list[str]:
        keys: list[str] = []
        strip = len(self._full_key("")) if self.prefix else 0
        for page in self.client().get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=self._full_key(prefix)):
            keys += [o["Key"][strip:] for o in page.get("Contents", [])]
        return sorted(keys)

    def test(self) -> tuple[bool, str]:
        if not self.configured:
            return False, "Credenciais AWS/bucket não informados."
        try:
            self.client().head_bucket(Bucket=self.bucket)
            return True, f"Bucket '{self.bucket}' acessível na região {self.region}."
        except Exception as exc:  # noqa: BLE001
            return False, f"Falha no S3: {exc}"


class FTPBackend:
    def __init__(self, settings: dict[str, str], timeout: int = 15):
        self.host = settings.get("FTP_HOST", "")
        self.port = int(settings.get("FTP_PORT") or 21)
        self.user = settings.get("FTP_USER", "")
        self.password = settings.get("FTP_PASSWORD", "")
        self.base_dir = settings.get("FTP_BASE_DIR") or "/backup_obra"
        self.use_tls = str(settings.get("FTP_TLS", "0")).lower() in ("1", "true", "sim", "yes")
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.host and self.user)

    def connect(self) -> ftplib.FTP:
        ftp: ftplib.FTP = ftplib.FTP_TLS() if self.use_tls else ftplib.FTP()
        ftp.connect(self.host, self.port, timeout=self.timeout)
        ftp.login(self.user, self.password)
        if self.use_tls and isinstance(ftp, ftplib.FTP_TLS):
            ftp.prot_p()
        return ftp

    @staticmethod
    def _ensure_dirs(ftp: ftplib.FTP, path: str) -> None:
        ftp.cwd("/")
        for part in [p for p in path.split("/") if p]:
            try:
                ftp.cwd(part)
            except ftplib.error_perm:
                ftp.mkd(part)
                ftp.cwd(part)

    def upload(self, key: str, data: bytes) -> None:
        remote = posixpath.join(self.base_dir, key)
        ftp = self.connect()
        try:
            self._ensure_dirs(ftp, posixpath.dirname(remote))
            ftp.storbinary(f"STOR {posixpath.basename(remote)}", io.BytesIO(data))
        finally:
            try:
                ftp.quit()
            except Exception:  # noqa: BLE001
                ftp.close()

    def download(self, key: str) -> bytes:
        buf = io.BytesIO()
        ftp = self.connect()
        try:
            ftp.retrbinary(f"RETR {posixpath.join(self.base_dir, key)}", buf.write)
        finally:
            try:
                ftp.quit()
            except Exception:  # noqa: BLE001
                ftp.close()
        return buf.getvalue()

    def delete(self, key: str) -> None:
        ftp = self.connect()
        try:
            ftp.delete(posixpath.join(self.base_dir, key))
        finally:
            try:
                ftp.quit()
            except Exception:  # noqa: BLE001
                ftp.close()

    def list_files(self, prefix: str) -> list[str]:
        """Chaves (relativas ao diretório base) de todos os arquivos sob ``prefix``, recursivo."""
        found: list[str] = []
        ftp = self.connect()

        def walk(rel: str) -> None:
            path = posixpath.join(self.base_dir, rel)
            try:
                entries = list(ftp.mlsd(path, facts=["type"]))
                for name, facts in entries:
                    if name in (".", ".."):
                        continue
                    child = posixpath.join(rel, name)
                    if facts.get("type") == "dir":
                        walk(child)
                    elif facts.get("type", "file") == "file":
                        found.append(child)
            except ftplib.error_perm:
                try:
                    names = ftp.nlst(path)
                except ftplib.error_perm:
                    return
                for full in names:
                    name = posixpath.basename(full.rstrip("/"))
                    child = posixpath.join(rel, name)
                    if "." in name:
                        found.append(child)
                    else:
                        walk(child)

        try:
            walk(prefix)
        finally:
            try:
                ftp.quit()
            except Exception:  # noqa: BLE001
                ftp.close()
        return sorted(found)

    def test_write(self) -> tuple[bool, str]:
        """Login + gravação + leitura + exclusão de um arquivo de teste (confirma permissão de escrita)."""
        ok, msg = self.test()
        if not ok:
            return ok, msg
        key, payload = "backup-banco/.teste_conexao", datetime.now().isoformat().encode()
        try:
            self.upload(key, payload)
            if self.download(key) != payload:
                return False, msg + " | Conteúdo lido difere do gravado."
            self.delete(key)
        except Exception as exc:  # noqa: BLE001
            return False, msg + f" | Sem permissão de gravação em {self.base_dir}/backup-banco: {exc}"
        return True, msg + f" | Gravação e leitura confirmadas em {self.base_dir}/backup-banco."

    def test(self) -> tuple[bool, str]:
        if not self.configured:
            return False, "Host/usuário do FTP não informados."
        try:
            ftp = self.connect()
            welcome = (ftp.getwelcome() or "").strip()
            cwd = ftp.pwd()
            ftp.quit()
            return True, f"Conectado a {self.host}:{self.port} ({'FTPS' if self.use_tls else 'FTP'}). {welcome} | dir: {cwd}"
        except Exception as exc:  # noqa: BLE001
            return False, f"Falha no FTP {self.host}:{self.port}: {exc}"


class DualStorage:
    def __init__(self, settings: dict[str, str] | None = None, local_root: Path | None = None,
                 remote: bool = True):
        settings = settings if settings is not None else load_connection_settings()
        self.local_root = Path(local_root or media_dir())
        self.s3 = S3Backend(settings)
        self.ftp = FTPBackend(settings)
        self.remote = remote

    def local_path(self, key: str) -> Path:
        return self.local_root / key

    def save(self, data: bytes, filename: str, category: str = "geral",
             when: datetime | None = None, key: str | None = None) -> StorageResult:
        key = key or build_key(category, filename, when)
        content_type = mimetypes.guess_type(filename)[0]
        result = StorageResult(key=key, size=len(data))

        path = self.local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

        if not self.remote:
            return result

        jobs = {}
        with ThreadPoolExecutor(max_workers=2) as pool:
            if self.s3.configured:
                jobs["s3"] = pool.submit(self.s3.upload, key, data, content_type)
            if self.ftp.configured:
                jobs["ftp"] = pool.submit(self.ftp.upload, key, data)
            for name, future in jobs.items():
                try:
                    future.result()
                    setattr(result, name, OK)
                except Exception as exc:  # noqa: BLE001
                    setattr(result, name, "erro")
                    result.errors.append(f"{name.upper()}: {exc}")
        return result

    def load(self, key: str) -> bytes | None:
        path = self.local_path(key)
        if path.exists():
            return path.read_bytes()
        for backend in (self.s3, self.ftp):
            if backend.configured:
                try:
                    data = backend.download(key)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    return data
                except Exception:  # noqa: BLE001
                    continue
        return None


def store_media(data: bytes, filename: str, category: str, *, remote: bool = True,
                when: datetime | None = None, storage: DualStorage | None = None) -> StorageResult:
    """Salva a mídia no armazenamento duplo e registra o resultado na tabela ``media``."""
    from erp.db import execute, now_iso

    storage = storage or DualStorage(remote=remote)
    result = storage.save(data, filename, category, when=when)
    execute(
        "INSERT INTO media(key, category, filename, content_type, size_bytes, local_status, s3_status, ftp_status, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (result.key, category, filename, mimetypes.guess_type(filename)[0], result.size,
         result.local, result.s3, result.ftp, (when or datetime.now()).isoformat(sep=" ", timespec="seconds")
         if when else now_iso()),
    )
    return result


def load_media(key: str | None) -> bytes | None:
    if not key:
        return None
    return DualStorage().load(key)
