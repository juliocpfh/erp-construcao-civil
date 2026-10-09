"""Telas de conta fora do login: primeiro acesso, solicitar acesso, esqueci a senha e 'Minha conta'."""
from __future__ import annotations

import streamlit as st

from erp import auth
from erp.services import accounts, mailer
from erp.ui.common import inject_css

VIEW_KEY = "auth_view"


def go(view: str | None) -> None:
    st.session_state[VIEW_KEY] = view
    st.rerun()


def current_view() -> str | None:
    return st.session_state.get(VIEW_KEY)


def auth_links(prefix: str) -> None:
    """Botões 'Esqueci minha senha' e 'Solicitar acesso' (sidebar e área principal, para o celular)."""
    c1, c2 = st.columns(2)
    if c1.button("🔑 Esqueci minha senha", key=f"{prefix}_forgot", width="stretch"):
        go("forgot")
    if c2.button("📝 Solicitar acesso", key=f"{prefix}_signup", width="stretch"):
        go("signup")


def _back() -> None:
    if st.button("← Voltar ao login"):
        go(None)


# --------------------------------------------------------------------------- primeiro acesso
def first_setup_screen() -> None:
    inject_css()
    code = st.session_state.get("recovery_code")
    if code:
        _show_recovery_code(code, first_time=True)
        return
    st.title("👋 Bem-vindo! Vamos criar o administrador")
    st.write("Instalação nova: defina o seu login e a sua senha de administrador. "
             "Depois você cadastra a equipe em **Administração → Gestão de Usuários**.")
    with st.form("first_setup"):
        name = st.text_input("Seu nome completo *")
        c1, c2 = st.columns(2)
        login = c1.text_input("Login *", value="admin")
        email = c2.text_input("E-mail (recomendado: recebe o código se esquecer a senha)")
        c1, c2 = st.columns(2)
        pw = c1.text_input("Senha * (mínimo 8 caracteres, com letra e número)", type="password")
        pw2 = c2.text_input("Confirmar senha *", type="password")
        ok = st.form_submit_button("Criar administrador", type="primary")
    if ok:
        try:
            code = accounts.complete_first_setup(login, name, email, pw, pw2)
        except accounts.AccountError as exc:
            st.error(str(exc))
            return
        st.session_state["recovery_code"] = code
        st.session_state["setup_login"] = (login.strip().lower(), pw)
        st.rerun()


def _show_recovery_code(code: str, first_time: bool = False) -> None:
    st.title("🛟 Guarde seu código de recuperação")
    st.write("Se você esquecer a senha de administrador, este código permite criar uma senha nova "
             "(tela de login → **Esqueci minha senha** → **Sou o administrador**). Ele aparece **só agora**: "
             "anote, imprima ou baixe o arquivo e guarde fora do computador.")
    st.code(code, language=None)
    st.download_button("⬇️ Baixar código (.txt)", f"ERP Obras - código de recuperação do administrador\n{code}\n",
                       file_name="erp_obras_codigo_recuperacao.txt")
    if st.checkbox("Guardei o código em lugar seguro"):
        if st.button("Continuar", type="primary"):
            st.session_state.pop("recovery_code", None)
            if first_time and (creds := st.session_state.pop("setup_login", None)):
                st.session_state["user"] = auth.authenticate(*creds)
            go(None)


# --------------------------------------------------------------------------- solicitar acesso
def signup_screen() -> None:
    st.subheader("📝 Solicitar acesso")
    st.write("Preencha seus dados. O administrador recebe o pedido, escolhe o seu perfil e libera os módulos; "
             "depois é só entrar com o login e a senha que você criou aqui.")
    with st.form("signup", clear_on_submit=False):
        name = st.text_input("Nome completo *")
        c1, c2 = st.columns(2)
        login = c1.text_input("Login desejado * (sem espaços, ex.: joao.silva)")
        email = c2.text_input("E-mail *")
        c1, c2 = st.columns(2)
        pw = c1.text_input("Senha * (mínimo 8, com letra e número)", type="password")
        pw2 = c2.text_input("Confirmar senha *", type="password")
        note = st.text_input("Função na obra / mensagem ao administrador")
        ok = st.form_submit_button("Enviar solicitação", type="primary")
    if ok:
        try:
            accounts.request_access(login, name, email, pw, pw2, note)
        except (accounts.AccountError, auth.AuthError) as exc:
            st.error(str(exc))
        else:
            st.success("Solicitação enviada! Aguarde a liberação pelo administrador.")
    _back()


# --------------------------------------------------------------------------- esqueci a senha
def forgot_screen() -> None:
    st.subheader("🔑 Esqueci minha senha")
    tabs = st.tabs(["📧 Receber código por e-mail", "🙋 Pedir ao administrador", "🛟 Sou o administrador"])
    with tabs[0]:
        if not mailer.configured():
            st.info("O envio de e-mail ainda não foi configurado pelo administrador. Use **Pedir ao administrador**.")
        else:
            with st.form("reset_req"):
                who = st.text_input("Seu login ou e-mail")
                if st.form_submit_button("Enviar código"):
                    try:
                        st.success(accounts.request_reset_by_email(who))
                        st.session_state["reset_who"] = who
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Não foi possível enviar o e-mail: {exc}")
            with st.form("reset_code"):
                st.markdown("**Recebeu o código? Crie a senha nova:**")
                who2 = st.text_input("Login ou e-mail", value=st.session_state.get("reset_who", ""))
                code = st.text_input("Código de 6 dígitos")
                c1, c2 = st.columns(2)
                pw = c1.text_input("Nova senha", type="password")
                pw2 = c2.text_input("Confirmar nova senha", type="password")
                if st.form_submit_button("Redefinir senha", type="primary"):
                    try:
                        accounts.reset_with_code(who2, code, pw, pw2)
                    except accounts.AccountError as exc:
                        st.error(str(exc))
                    else:
                        st.success("Senha redefinida. Faça login com a senha nova.")
    with tabs[1]:
        with st.form("reset_admin"):
            who = st.text_input("Seu login ou e-mail ")
            note = st.text_input("Mensagem (opcional)")
            if st.form_submit_button("Pedir nova senha ao administrador"):
                st.success(accounts.request_reset_by_admin(who, note))
    with tabs[2]:
        st.caption("Use o código de recuperação que apareceu quando o administrador foi criado.")
        with st.form("reset_recovery"):
            who = st.text_input("Login do administrador")
            code = st.text_input("Código de recuperação (ex.: 1A2B-3C4D-5E6F-7A8B)")
            c1, c2 = st.columns(2)
            pw = c1.text_input("Nova senha ", type="password")
            pw2 = c2.text_input("Confirmar nova senha ", type="password")
            ok = st.form_submit_button("Redefinir senha do administrador", type="primary")
        if ok:
            try:
                st.session_state["recovery_code"] = accounts.reset_admin_with_recovery_code(who, code, pw, pw2)
            except accounts.AccountError as exc:
                st.error(str(exc))
            else:
                go("new_recovery")
    _back()


def new_recovery_screen() -> None:
    st.success("Senha do administrador redefinida. O código antigo deixou de valer; guarde o novo abaixo.")
    _show_recovery_code(st.session_state.get("recovery_code", ""))


# --------------------------------------------------------------------------- minha conta (logado)
def my_account(user: dict) -> None:
    with st.popover("⚙️ Minha conta", width="stretch"):
        with st.form("profile"):
            name = st.text_input("Nome", user["full_name"] or "")
            email = st.text_input("E-mail (para recuperar a senha)", user.get("email") or "")
            if st.form_submit_button("Salvar dados"):
                try:
                    accounts.update_profile(user["id"], name, email)
                    st.success("Dados salvos.")
                except accounts.AccountError as exc:
                    st.error(str(exc))
        with st.form("own_pw", clear_on_submit=True):
            cur = st.text_input("Senha atual", type="password")
            pw = st.text_input("Nova senha", type="password")
            pw2 = st.text_input("Confirmar nova senha", type="password")
            if st.form_submit_button("Trocar senha"):
                try:
                    accounts.change_own_password(user["id"], cur, pw, pw2)
                    st.success("Senha alterada.")
                except accounts.AccountError as exc:
                    st.error(str(exc))
