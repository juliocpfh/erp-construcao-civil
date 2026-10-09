"""ERP de Gestão de Obras — ponto de entrada do Streamlit (Community Cloud: main file = app.py)."""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="ERP Obras · PMO", page_icon="🏗️", layout="wide", initial_sidebar_state="expanded")

from erp import auth, db  # noqa: E402
from erp.config import ADMIN_PAGES, MODULES, PROJECT_NAME, ROLE_ADMIN  # noqa: E402
from erp.security import password_policy_errors  # noqa: E402
from erp.ui import (  # noqa: E402
    page_admin, page_connections, page_contacts, page_dashboard, page_environment, page_fiscal, page_ged,
    page_inventory, page_media, page_rdo, page_schedule, page_wbs,
)
from erp.ui.common import inject_css  # noqa: E402

RENDERERS = {
    "painel": page_dashboard.render, "eap": page_wbs.render, "cronograma": page_schedule.render,
    "rdo": page_rdo.render, "fiscal": page_fiscal.render, "estoque": page_inventory.render,
    "midia": page_media.render, "ambiental": page_environment.render, "ged": page_ged.render,
    "contatos": page_contacts.render, "usuarios": page_admin.render, "conexoes": page_connections.render,
}
SECTIONS = {
    "Gestão": ["painel", "eap", "cronograma", "fiscal"],
    "Campo": ["rdo", "estoque", "midia", "ambiental"],
    "Documentos": ["ged", "contatos"],
    "Administração": ["usuarios", "conexoes"],
}


@st.cache_resource(show_spinner="Preparando banco de dados e massa de simulação (primeira execução)...")
def bootstrap() -> bool:
    from erp.seed import seed_database

    db.init_db()
    if not db.is_seeded():
        seed_database()
    return True


def login_sidebar() -> None:
    with st.sidebar:
        st.markdown(f"### 🏗️ ERP Obras\n{PROJECT_NAME}")
        with st.form("login"):
            username = st.text_input("Usuário")
            password = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar", type="primary", width="stretch"):
                user = auth.authenticate(username, password)
                if user:
                    st.session_state["user"] = user
                    st.rerun()
                st.error("Usuário ou senha inválidos (ou usuário inativo).")


def landing() -> None:
    inject_css()
    st.title("🏗️ ERP de Gestão de Obras · PMO de Engenharia Civil")
    st.markdown(
        f"**{PROJECT_NAME}** — edifício residencial de 10 pavimentos. Faça login na barra lateral "
        "(no celular, toque em **›** no canto superior esquerdo).")
    st.markdown("""
| Perfil | Usuário | Senha | Acesso |
|---|---|---|---|
| Administrador | `admin` | `admin123` | Tudo + usuários + conexões/backup |
| Almoxarife | `almoxarife` | `campo123` | Somente estoque e consumo diário |
| Visualizador | `visualizador` | `visual123` | Leitura dos módulos de gestão |
| Visualizador (senha provisória) | `fiscal.banco` | `Prov@2026` | Troca de senha obrigatória |
""")
    c = st.columns(3)
    c[0].info("📊 CPM, Gantt, Curva S, IDC/IDP")
    c[1].info("📸 OCR de NF, almoxarifado e RDO")
    c[2].info("🌲 Araucárias, GED, vCard, S3 + FTP")


def change_password_screen(user: dict) -> None:
    inject_css()
    st.title("🔑 Troca de senha obrigatória")
    st.write(f"Olá, **{user['full_name']}**. Sua senha é provisória; defina uma nova senha para continuar.")
    with st.form("pw"):
        new = st.text_input("Nova senha", type="password")
        confirm = st.text_input("Confirmar nova senha", type="password")
        if st.form_submit_button("Alterar senha", type="primary"):
            errors = password_policy_errors(new)
            if new != confirm:
                st.error("As senhas não conferem.")
            elif errors:
                st.error("Senha fraca: " + ", ".join(errors))
            else:
                auth.change_password(user["id"], new)
                st.session_state["user"] = auth.get_user(user["id"])
                st.success("Senha alterada.")
                st.rerun()


def main() -> None:
    bootstrap()
    session_user = st.session_state.get("user")
    user = auth.get_user(session_user["id"]) if session_user else None
    if session_user and (not user or not user["active"]):
        st.session_state.pop("user", None)
        user = None
    if not user:
        login_sidebar()
        landing()
        return
    st.session_state["user"] = user  # perfil/permissões recarregados a cada interação

    with st.sidebar:
        st.markdown(f"**👤 {user['full_name']}**  \n{user['role']} · `{user['username']}`")
        if st.button("Sair", icon=":material/logout:", width="stretch"):
            st.session_state.clear()
            st.rerun()

    if user["must_change_password"]:
        change_password_screen(user)
        return

    allowed = auth.allowed_pages(user)
    catalog = {**MODULES, **ADMIN_PAGES}
    nav: dict[str, list] = {}
    for section, keys in SECTIONS.items():
        pages = [st.Page(RENDERERS[k], title=catalog[k][0], icon=catalog[k][1], url_path=k)
                 for k in keys if k in allowed]
        if pages:
            nav[section] = pages
    if not nav:
        st.warning("Seu usuário ainda não tem módulos liberados. Fale com o Administrador.")
        return
    inject_css()
    page = st.navigation(nav, expanded=user["role"] == ROLE_ADMIN)
    page.run()


main()
