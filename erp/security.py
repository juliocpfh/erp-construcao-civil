"""Hash de senhas (PBKDF2) e criptografia simétrica (Fernet) dos segredos de conexão."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from erp.config import data_dir

PBKDF2_ITERATIONS = 200_000
ENC_PREFIX = "enc:"


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_b64, digest_b64 = stored.split("$")
    except (ValueError, AttributeError):
        return False
    if algo != "pbkdf2_sha256":
        return False
    salt = base64.b64decode(salt_b64)
    expected = base64.b64decode(digest_b64)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(candidate, expected)


def password_policy_errors(password: str) -> list[str]:
    errors = []
    if len(password) < 8:
        errors.append("mínimo de 8 caracteres")
    if not any(c.isdigit() for c in password):
        errors.append("ao menos um número")
    if not any(c.isalpha() for c in password):
        errors.append("ao menos uma letra")
    return errors


def _master_key_file() -> Path:
    return Path(os.environ.get("ERP_MASTER_KEY_FILE", data_dir() / ".master.key"))


def _secrets_master_key() -> str | None:
    try:  # st.secrets só existe dentro do Streamlit
        import streamlit as st

        return st.secrets.get("ERP_MASTER_KEY")  # type: ignore[no-any-return]
    except Exception:
        return None


def get_master_key() -> bytes:
    """Chave mestra: ERP_MASTER_KEY (env ou st.secrets) ou arquivo local gerado na 1ª execução."""
    key = os.environ.get("ERP_MASTER_KEY") or _secrets_master_key()
    if key:
        return key.encode()
    key_file = _master_key_file()
    if key_file.exists():
        return key_file.read_bytes().strip()
    new_key = Fernet.generate_key()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(new_key)
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return new_key


def get_fernet() -> Fernet:
    return Fernet(get_master_key())


def encrypt_value(value: str) -> str:
    if value is None or value == "":
        return ""
    return ENC_PREFIX + get_fernet().encrypt(str(value).encode()).decode()


def decrypt_value(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(ENC_PREFIX):
        return value  # valor legado em texto puro
    try:
        return get_fernet().decrypt(value[len(ENC_PREFIX):].encode()).decode()
    except InvalidToken:
        return ""
