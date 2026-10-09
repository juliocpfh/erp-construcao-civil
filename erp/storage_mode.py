"""Onde fica o banco de dados: 'local' (disco deste computador) ou 'ftp' (servidor FTP do usuário).

A escolha fica em ``data/storage_mode.json`` (fora do banco, porque o banco pode vir do FTP) ou na
variável/secret ``ERP_STORAGE_MODE``. Sem escolha explícita o app se comporta como 'ftp' quando há
FTP configurado e o administrador é convidado a escolher no primeiro login.
"""
from __future__ import annotations

import json
import os

from erp.config import data_dir

LOCAL = "local"
FTP = "ftp"
MODES = {
    LOCAL: "💻 Neste computador (disco local)",
    FTP: "🌐 No meu servidor FTP",
}
LOCAL_WARNING = ("O banco de dados e os arquivos ficam SOMENTE no disco deste computador. O sistema NÃO será "
                 "acessível pelo celular nem remotamente, e outras pessoas não conseguem usá-lo. Se o computador "
                 "estragar ou for formatado, os dados se perdem: baixe uma cópia do banco com frequência.")
FTP_INFO = ("O banco de dados e os arquivos ficam no seu FTP. Quem tiver o endereço (link) do sistema publicado "
            "acessa pelo computador ou celular, de qualquer lugar, de acordo com o nível de acesso do seu usuário, "
            "inclusive vendo apenas as pastas de documentos liberadas para ele.")
FTP_CAVEAT = ("Se o sistema estiver aberto em dois lugares que gravam no mesmo FTP (ex.: este computador e o site), "
              "evite lançar dados nos dois ao mesmo tempo: o sistema sincroniza a versão mais recente e, se houver "
              "lançamentos simultâneos, avisa e pede para escolher qual versão manter.")


def _path():
    return data_dir() / "storage_mode.json"


def get_mode() -> str | None:
    value = os.environ.get("ERP_STORAGE_MODE")
    if value is None:
        try:
            import streamlit as st

            value = st.secrets.get("ERP_STORAGE_MODE")
        except Exception:
            value = None
    if value and str(value).strip().lower() in MODES:
        return str(value).strip().lower()
    try:
        mode = json.loads(_path().read_text(encoding="utf-8")).get("mode")
    except (OSError, ValueError):
        return None
    return mode if mode in MODES else None


def set_mode(mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"Modo inválido: {mode}")
    _path().write_text(json.dumps({"mode": mode}), encoding="utf-8")


def is_local() -> bool:
    return get_mode() == LOCAL


def effective_mode() -> str | None:
    """Modo escolhido; sem escolha, 'ftp' quando há FTP configurado (ex.: Secrets do Streamlit Cloud)."""
    mode = get_mode()
    if mode:
        return mode
    from erp.settings_store import load_connection_settings
    from erp.storage import FTPBackend

    return FTP if FTPBackend(load_connection_settings()).configured else None


def ftp_from_environment() -> bool:
    """FTP definido fora da tela (Secrets do Streamlit Cloud / variáveis): servidor já decidido."""
    if os.environ.get("FTP_HOST"):
        return True
    try:
        import streamlit as st

        return bool(st.secrets.get("FTP_HOST"))
    except Exception:
        return False


def needs_choice() -> bool:
    """O administrador ainda precisa escolher onde fica o banco (primeiro login)."""
    return get_mode() is None and not ftp_from_environment()
