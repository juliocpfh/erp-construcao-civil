"""Painel do Administrador: usuários, perfis, permissões por checkbox e senha provisória."""
from __future__ import annotations

import secrets

import pandas as pd
import streamlit as st

from erp import auth
from erp.config import MODULES, ROLE_ADMIN, ROLES
from erp.ui.common import current_user, header


def render() -> None:
    if not auth.is_admin(current_user()):
        st.error("Acesso restrito ao Administrador.")
        st.stop()
    header("Gestão de Usuários e Acessos (RBAC)",
           "Marque os módulos liberados para cada usuário. Administradores têm acesso total.")
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

    c1, c2 = st.columns(2)
    with c1, st.form("new_user", clear_on_submit=True):
        st.subheader("➕ Novo usuário")
        username = st.text_input("Login")
        full = st.text_input("Nome completo")
        role = st.selectbox("Perfil", ROLES, index=2)
        temp = st.text_input("Senha provisória", value=f"Obra@{secrets.randbelow(9000) + 1000}")
        st.caption("O usuário será obrigado a trocar a senha no primeiro acesso.")
        if st.form_submit_button("Criar usuário", type="primary"):
            try:
                auth.create_user(username, temp, role, full, must_change_password=True)
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
