"""Leitura/escrita do arquivo .env com os segredos de conexão criptografados (Fernet)."""
from __future__ import annotations

import os
from pathlib import Path

from erp.config import env_path
from erp.security import ENC_PREFIX, decrypt_value, encrypt_value

# chave -> (rótulo, é segredo?)
CONNECTION_FIELDS: dict[str, tuple[str, bool]] = {
    "AWS_ACCESS_KEY_ID": ("AWS Access Key ID", True),
    "AWS_SECRET_ACCESS_KEY": ("AWS Secret Access Key", True),
    "AWS_REGION": ("Região AWS", False),
    "S3_BUCKET": ("Bucket S3 (Produção)", False),
    "S3_PREFIX": ("Prefixo no bucket", False),
    "FTP_HOST": ("IP / Host do FTP", False),
    "FTP_PORT": ("Porta FTP", False),
    "FTP_USER": ("Usuário FTP", True),
    "FTP_PASSWORD": ("Senha FTP", True),
    "FTP_BASE_DIR": ("Diretório base do backup", False),
    "FTP_TLS": ("Usar FTPS (TLS)", False),
}

DEFAULTS = {
    "AWS_REGION": "sa-east-1",
    "S3_PREFIX": "obra",
    "FTP_PORT": "21",
    "FTP_BASE_DIR": "/backup_obra",
    "FTP_TLS": "0",
}


def _parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key.strip()] = val
    return values


def read_raw_env(path: Path | None = None) -> dict[str, str]:
    path = path or env_path()
    if not path.exists():
        return {}
    return _parse_env(path.read_text(encoding="utf-8"))


def load_connection_settings(path: Path | None = None) -> dict[str, str]:
    """Mescla padrões < st.secrets < variáveis de ambiente < .env criptografado."""
    settings = dict(DEFAULTS)
    try:
        import streamlit as st

        for key in CONNECTION_FIELDS:
            if key in st.secrets:
                settings[key] = str(st.secrets[key])
    except Exception:
        pass
    for key in CONNECTION_FIELDS:
        if os.environ.get(key):
            settings[key] = os.environ[key]
    for key, val in read_raw_env(path).items():
        if key in CONNECTION_FIELDS and val != "":
            settings[key] = decrypt_value(val)
    return settings


def write_env(values: dict[str, str], path: Path | None = None) -> Path:
    """Reescreve o .env: todo valor de conexão é gravado criptografado (prefixo enc:)."""
    path = path or env_path()
    current = read_raw_env(path)
    merged = dict(current)
    for key, val in values.items():
        if key not in CONNECTION_FIELDS:
            continue
        if val is None:
            continue
        merged[key] = encrypt_value(str(val)) if str(val) != "" else ""
    # garante que nenhum valor de conexão permaneça em texto puro
    for key in list(merged):
        if key in CONNECTION_FIELDS and merged[key] and not merged[key].startswith(ENC_PREFIX):
            merged[key] = encrypt_value(merged[key])
    lines = [
        "# Arquivo gerado pelo ERP de Obras - valores criptografados com Fernet (AES-128-CBC + HMAC).",
        "# Não edite manualmente: use a aba 'Configurações de Conexão e Backup'.",
    ]
    lines += [f"{k}={v}" for k, v in merged.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "•" * len(value)
    return value[:2] + "•" * (len(value) - 4) + value[-2:]
