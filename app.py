"""ERP de Gestão de Obras — ponto de entrada do Streamlit (Community Cloud: main file = app.py)."""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="ERP Obras · PMO", page_icon="🏗️", layout="wide", initial_sidebar_state="expanded")

from erp import auth, db  # noqa: E402
from erp.config import ADMIN_PAGES, MODULES, ROLE_ADMIN  # noqa: E402
from erp.services import backup  # noqa: E402
from erp.services.project import project_info  # noqa: E402
from erp.security import password_policy_errors  # noqa: E402
from erp.ui import (  # noqa: E402
    page_admin, page_connections, page_contacts, page_dashboard, page_environment, page_fiscal, page_ged,
    page_inventory, page_media, page_project, page_rdo, page_schedule, page_wbs,
)
from erp.ui.common import ftp_problem_alert, inject_css  # noqa: E402

RENDERERS = {
    "painel": page_dashboard.render, "eap": page_wbs.render, "cronograma": page_schedule.render,
    "rdo": page_rdo.render, "fiscal": page_fiscal.render, "estoque": page_inventory.render,
    "midia": page_media.render, "ambiental": page_environment.render, "ged": page_ged.render,
    "contatos": page_contacts.render, "usuarios": page_admin.render, "conexoes": page_connections.render,
    "projeto": page_project.render,
}
SECTIONS = {
    "Gestão": ["painel", "eap", "cronograma", "fiscal"],
    "Campo": ["rdo", "estoque", "midia", "ambiental"],
    "Documentos": ["ged", "contatos"],
    "Administração": ["projeto", "usuarios", "conexoes"],
}


@st.cache_resource(show_spinner="Preparando banco de dados (primeira execução)...")
def bootstrap() -> bool:
    from erp.services import project

    db.init_db()
    if not db.is_seeded():
        backup.restore_latest_remote()  # disco efêmero: recupera o último backup do S3/FTP, se houver
    project.bootstrap()
    return True


def login_sidebar() -> None:
    with st.sidebar:
        st.markdown(f"### 🏗️ ERP Obras\n{project_info()['name']}")
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
    if msg := st.session_state.pop("restore_msg", None):
        st.success(msg)
    problem = backup.connection_problem()
    if problem and problem.get("startup"):
        st.warning("O banco de dados não pôde ser carregado do servidor FTP. O administrador deve entrar para "
                   "ver o passo a passo de correção.")
    info = project_info()
    st.markdown(f"**{info['name']}**" + (f" · {info['location']}" if info["location"] else ""))
    st.markdown("Faça login na barra lateral (no celular, toque em **›** no canto superior esquerdo).")
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
    by_key = {}
    for section, keys in SECTIONS.items():
        pages = [st.Page(RENDERERS[k], title=catalog[k][0], icon=catalog[k][1], url_path=k)
                 for k in keys if k in allowed]
        by_key.update({p.url_path: p for p in pages})
        if pages:
            nav[section] = pages
    if not nav:
        st.warning("Seu usuário ainda não tem módulos liberados. Fale com o Administrador.")
        return
    inject_css()
    page = st.navigation(nav, expanded=user["role"] == ROLE_ADMIN)
    if page.url_path != "projeto":  # na própria página do FTP o passo a passo aparece no topo
        ftp_problem_alert(backup.connection_problem(), user["role"] == ROLE_ADMIN, by_key.get("projeto"))
    page.run()
    backup.maybe_auto_backup()  # cópia do banco no S3/FTP, se configurados e se houve alteração


main()
