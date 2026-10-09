"""Dados do projeto (nome, local, início) e ciclo de vida: projeto novo em branco ou simulação de demonstração."""
from __future__ import annotations

import os
import shutil
from datetime import date

from erp import db
from erp.config import PROJECT_LOCATION, PROJECT_NAME, ROLE_ADMIN, media_dir

DEFAULT_ADMIN_PASSWORD = "admin123"


def project_info() -> dict:
    name, location = db.get_setting("project_name"), db.get_setting("project_location")
    return {
        "name": name or PROJECT_NAME,
        "location": location if location is not None else PROJECT_LOCATION,
        "description": db.get_setting("project_description") or "",
        "start": db.get_setting("project_start"),
    }


def _config(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        try:
            import streamlit as st

            value = str(st.secrets.get(name, ""))
        except Exception:
            value = ""
    return str(value).strip()


def demo_requested() -> bool:
    """ERP_DEMO=1 (variável de ambiente ou st.secrets) carrega a simulação na primeira execução."""
    return _config("ERP_DEMO").lower() in ("1", "true", "sim", "yes")


def wipe_all() -> None:
    """Apaga TODOS os dados (tabelas e mídias locais). Mídias já enviadas ao S3/FTP não são removidas."""
    db.init_db()
    with db.transaction() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        for t in tables:
            conn.execute(f'DELETE FROM "{t}"')
        if conn.execute("SELECT name FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone():
            conn.execute("DELETE FROM sqlite_sequence")
    shutil.rmtree(media_dir(), ignore_errors=True)
    media_dir()


def create_blank_project(name: str, location: str = "", start: date | None = None, description: str = "",
                         admin_password: str = DEFAULT_ADMIN_PASSWORD, admin_name: str = "Administrador",
                         must_change_password: bool = True, daily_indirect_cost: float = 0.0) -> None:
    """Zera o sistema e deixa apenas o usuário admin, pronto para cadastrar uma obra real."""
    from erp.auth import create_user

    wipe_all()
    for key, val in {
        "project_name": name.strip() or "Nova Obra",
        "project_location": location.strip(),
        "project_description": description.strip(),
        "project_start": (start or date.today()).isoformat(),
        "daily_indirect_cost": str(daily_indirect_cost),
        "araucaria_dap_factor": "12",
    }.items():
        db.set_setting(key, val)
    from erp.services.wbs import add_deliverable

    add_deliverable(None, name.strip() or "Nova Obra", "Raiz da EAP (obra)")
    create_user("admin", admin_password, ROLE_ADMIN, admin_name, must_change_password=must_change_password)


def load_demo() -> dict:
    """Zera o sistema e carrega a simulação do edifício de 10 pavimentos."""
    from erp.seed import seed_database

    wipe_all()
    return seed_database()


def bootstrap() -> None:
    """Primeira execução: projeto em branco (padrão) ou simulação (ERP_DEMO=1)."""
    db.init_db()
    if db.is_seeded():
        return
    if demo_requested():
        from erp.seed import seed_database

        seed_database()
    else:
        # ERP_ADMIN_PASSWORD (Secrets) evita a senha padrão pública num banco recém-criado
        initial = _config("ERP_ADMIN_PASSWORD")
        create_blank_project("Nova Obra", admin_password=initial or DEFAULT_ADMIN_PASSWORD,
                             must_change_password=not initial)
