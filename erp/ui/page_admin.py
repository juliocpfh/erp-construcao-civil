"""Painel do Administrador: usuários, perfis, permissões por checkbox e senha provisória."""
from __future__ import annotations

import secrets

import pandas as pd
import streamlit as st

from erp import auth
from erp.services import accounts
from erp.config import DEFAULT_PERMISSIONS, DOC_AREAS, MODULES, ROLE_ADMIN, ROLE_VIEWER, ROLES
from erp.ui.common import current_user, header


def render() -> None:
    if not auth.is_admin(current_user()):
        st.error("Acesso restrito ao Administrador.")
        st.stop()
    header("Gestão de Usuários e Acessos (RBAC)",
           "Marque os módulos liberados para cada usuário. Administradores têm acesso total.")
    _requests()
    users = auth.list_users()

    st.subheader("🔐 Matriz de permissões")
    rows = []
    for u in users:
        row = {"id": u["id"], "Usuário": u["username"], "Perfil": u["role"], "Ativo": bool(u["active"]),
               "Trocar senha": bool(u["must_change_password"])}
        for key, (title, _) in MODULES.items():
            row[title] = u["role"] == ROLE_ADMIN or key in u["permissions"]
        rows.append(row)
    df = pd.DataFrame(rows)
    edited = st.data_editor(
        df, hide_index=True, width="stretch", key="perm_matrix", disabled=["id", "Usuário"],
        column_config={"id": None, "Perfil": st.column_config.SelectboxColumn(options=ROLES, required=True),
                       **{title: st.column_config.CheckboxColumn(title) for title, _ in MODULES.values()}},
    )
    if st.button("💾 Salvar permissões", type="primary"):
        me = current_user()["id"]
        for _, r in edited.iterrows():
            uid = int(r["id"])
            if uid == me and (r["Perfil"] != ROLE_ADMIN or not r["Ativo"]):
                st.warning("Você não pode rebaixar ou desativar o próprio usuário.")
                continue
            auth.update_user(uid, role=r["Perfil"], active=bool(r["Ativo"]))
            auth.force_password_change(uid, bool(r["Trocar senha"]))
            auth.set_permissions(uid, [k for k, (title, _) in MODULES.items() if r[title]])
        st.success("Permissões atualizadas — valem no próximo carregamento de página de cada usuário.")
        st.rerun()

    _doc_access(users)

    c1, c2 = st.columns(2)
    with c1, st.form("new_user", clear_on_submit=True):
        st.subheader("➕ Novo usuário")
        username = st.text_input("Login")
        full = st.text_input("Nome completo")
        email = st.text_input("E-mail (recuperação de senha)")
        role = st.selectbox("Perfil", ROLES, index=2)
        temp = st.text_input("Senha provisória", value=f"Obra@{secrets.randbelow(9000) + 1000}")
        st.caption("O usuário será obrigado a trocar a senha no primeiro acesso.")
        if st.form_submit_button("Criar usuário", type="primary"):
            try:
                uid = auth.create_user(username, temp, role, full, must_change_password=True)
                if email.strip():
                    accounts.update_profile(uid, full or username, email)
                st.success(f"Usuário criado. Senha provisória: {temp}")
            except auth.AuthError as exc:
                st.error(str(exc))
    with c2, st.form("reset_pw"):
        st.subheader("🔑 Forçar troca de senha provisória")
        opts = {f"{u['username']} ({u['role']})": u["id"] for u in users}
        sel = st.selectbox("Usuário", list(opts))
        temp = st.text_input("Nova senha provisória", value=f"Temp@{secrets.randbelow(9000) + 1000}")
        if st.form_submit_button("Definir senha provisória"):
            auth.set_temporary_password(opts[sel], temp)
            st.success(f"Senha provisória definida ({temp}). Troca obrigatória no próximo login.")


def _doc_access(users: list[dict]) -> None:
    st.subheader("📂 Acesso a documentos por usuário")
    st.caption("Marque as pastas do GED e as categorias de leis que cada usuário pode ver e baixar "
               "(além do módulo estar liberado na matriz acima). Administradores veem tudo.")
    others = [u for u in users if u["role"] != ROLE_ADMIN]
    if not others:
        st.info("Cadastre usuários para definir o acesso aos documentos.")
        return
    rows = []
    for u in others:
        areas = auth.doc_areas(u)
        rows.append({"id": u["id"], "Usuário": u["username"], **{label: key in areas for key, label in DOC_AREAS.items()}})
    edited = st.data_editor(
        pd.DataFrame(rows), hide_index=True, width="stretch", key="doc_matrix", disabled=["id", "Usuário"],
        column_config={"id": None, **{label: st.column_config.CheckboxColumn(label) for label in DOC_AREAS.values()}},
    )
    if st.button("💾 Salvar acesso a documentos"):
        for _, r in edited.iterrows():
            auth.set_doc_areas(int(r["id"]), [key for key, label in DOC_AREAS.items() if r[label]])
        st.success("Acesso a documentos atualizado.")
        st.rerun()


def _requests() -> None:
    pending = accounts.pending_requests()
    resets = accounts.open_admin_reset_requests()
    if not pending and not resets:
        _recovery_code_box()
        return
    st.subheader(f"📥 Pedidos aguardando você ({len(pending) + len(resets)})")
    for r in pending:
        with st.container(border=True):
            st.markdown(f"**Solicitação de acesso:** {r['full_name']} · `{r['username']}` · {r['email']}  \n"
                        f"{r['request_note'] or ''} · pedido em {r['created_at'][:16]}")
            c1, c2, c3, c4 = st.columns([1.2, 2.5, 1, 1])
            role = c1.selectbox("Perfil", ROLES, index=ROLES.index(ROLE_VIEWER), key=f"rq_role_{r['id']}")
            mods = c2.multiselect("Módulos liberados", list(MODULES), format_func=lambda k: MODULES[k][0],
                                  default=list(DEFAULT_PERMISSIONS[role]), key=f"rq_mods_{r['id']}")
            if c3.button("✅ Aprovar", key=f"rq_ok_{r['id']}", type="primary"):
                accounts.approve_request(r["id"], role, mods)
                st.rerun()
            if c4.button("❌ Recusar", key=f"rq_no_{r['id']}"):
                accounts.reject_request(r["id"])
                st.rerun()
    for r in resets:
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"**Esqueceu a senha:** {r['full_name']} · `{r['username']}` · pedido em {r['created_at'][:16]}")
            if c2.button("Gerar senha provisória", key=f"rs_{r['id']}", type="primary"):
                temp = accounts.resolve_admin_reset(r["id"], current_user()["username"])
                st.session_state["last_temp"] = (r["username"], temp, bool(r["email"]))
                st.rerun()
    if last := st.session_state.pop("last_temp", None):
        st.success(f"Senha provisória de **{last[0]}**: `{last[1]}` — informe ao usuário"
                   + (" (também enviada por e-mail, se o SMTP estiver configurado)." if last[2] else ".")
                   + " Ele cria uma senha nova no próximo login.")
    _recovery_code_box()


def _recovery_code_box() -> None:
    with st.expander("🛟 Código de recuperação do administrador"):
        st.write("Permite redefinir a senha do administrador pela tela de login se ela for esquecida. "
                 + ("Já existe um código ativo." if accounts.has_recovery_code() else "**Ainda não há código: gere um.**"))
        if st.button("Gerar novo código (o anterior deixa de valer)"):
            st.session_state["admin_new_code"] = accounts.regenerate_recovery_code()
        if code := st.session_state.pop("admin_new_code", None):
            st.code(code, language=None)
            st.download_button("⬇️ Baixar código (.txt)", f"ERP Obras - código de recuperação do administrador\n{code}\n",
                               file_name="erp_obras_codigo_recuperacao.txt")
            st.warning("Guarde agora: o código não será mostrado de novo.")
