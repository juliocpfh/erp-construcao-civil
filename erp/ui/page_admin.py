"""Painel do Administrador: usuários, perfis, permissões por checkbox e senha provisória."""
from __future__ import annotations

import secrets

import pandas as pd
import streamlit as st

from erp import auth
from erp.config import DOC_AREAS, MODULES, ROLE_ADMIN, ROLES
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

    _doc_access(users)

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
