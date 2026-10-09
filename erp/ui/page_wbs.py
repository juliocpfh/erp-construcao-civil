"""WBS / EAP multi-visualização: Árvore Graphviz, Tabela Recuada (MindView) e Kanban."""
from __future__ import annotations

import streamlit as st

from erp import db
from erp.config import WBS_STATUS
from erp.services import wbs as wbs_service
from erp.ui.common import can_edit, header, money, read_only_notice

VIEWS = ["🌳 Árvore Gráfica", "📑 Tabela Recuada (MindView)", "🗂️ Kanban de Entregas"]


def _kanban(df) -> None:
    editable = can_edit()
    leaves = df[df["level"] >= 1]
    cols = st.columns(3)
    icons = {"A Fazer": "⏳", "Em Andamento": "🚧", "Concluído": "✅"}
    for col, status in zip(cols, WBS_STATUS):
        items = leaves[leaves["status"] == status]
        with col:
            st.markdown(f"#### {icons[status]} {status} ({len(items)})")
            for row in items.itertuples():
                with st.container(border=True):
                    st.markdown(f"**{row.code} · {row.name}**")
                    st.caption(f"{row.responsible or '-'} · {money(row.budget)}")
                    st.progress(min(max(row.progress / 100, 0.0), 1.0), text=f"{row.progress:.0f}%")
                    if editable:
                        idx = WBS_STATUS.index(status)
                        b1, b2 = st.columns(2)
                        if idx > 0 and b1.button("◀", key=f"kb_l_{row.id}", help=f"Mover para {WBS_STATUS[idx - 1]}"):
                            wbs_service.set_status(int(row.id), WBS_STATUS[idx - 1])
                            st.rerun()
                        if idx < 2 and b2.button("▶", key=f"kb_r_{row.id}", help=f"Mover para {WBS_STATUS[idx + 1]}"):
                            wbs_service.set_status(int(row.id), WBS_STATUS[idx + 1])
                            st.rerun()


def render() -> None:
    header("WBS / EAP — Estrutura Analítica do Projeto", "Cadastro de entregas com três visualizações alternáveis.")
    df = wbs_service.load_wbs()
    view = st.segmented_control("Visualização", VIEWS, default=VIEWS[0], key="wbs_view") or VIEWS[0]

    if df.empty:
        st.info("Nenhuma entrega cadastrada ainda. Use **➕ Nova entrega** abaixo: comece pela obra (raiz) e "
                "depois cadastre as etapas (Fundação, Estrutura, Alvenaria...) como filhas dela.")
    elif view == VIEWS[0]:
        c1, c2 = st.columns([1, 1])
        max_level = int(df["level"].max())
        level = c1.slider("Níveis exibidos", 0, max_level, max_level) if max_level > 0 else 0
        horizontal = c2.toggle("Orientação horizontal (árvore deitada)", value=True)
        st.graphviz_chart(wbs_service.graphviz_tree(df, level, horizontal), width="stretch")
        st.caption("Cores: cinza = A Fazer · amarelo = Em Andamento · verde = Concluído. % = avanço ponderado pelo custo.")
    elif view == VIEWS[1]:
        st.dataframe(
            wbs_service.indented_table(df), hide_index=True, width="stretch", height=620,
            column_config={
                "Avanço": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f%%"),
                "Orçamento (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
            },
        )
    else:
        _kanban(df)

    st.divider()
    if not can_edit():
        read_only_notice()
        return
    c1, c2 = st.columns(2)
    with c1, st.form("wbs_new", clear_on_submit=True):
        st.markdown("##### ➕ Nova entrega")
        parents = {f"{r.code} · {r.name}": int(r.id) for r in df.itertuples()}
        parent = st.selectbox("Entrega pai", ["(raiz)"] + list(parents), index=1 if parents else 0)
        name = st.text_input("Nome da entrega")
        desc = st.text_area("Descrição / critério de aceite", height=80)
        contacts = {c["name"]: c["id"] for c in db.query("SELECT id, name FROM contacts ORDER BY name")}
        resp = st.selectbox("Responsável", ["-"] + list(contacts))
        if st.form_submit_button("Cadastrar entrega", type="primary"):
            if not name.strip():
                st.error("Informe o nome da entrega.")
            else:
                wbs_service.add_deliverable(parents.get(parent), name.strip(), desc, contacts.get(resp))
                st.success("Entrega cadastrada.")
                st.rerun()
    with c2:
        st.markdown("##### 🔄 Status")
        st.write("Sincroniza o status de todas as entregas a partir do avanço físico das tarefas do cronograma.")
        if st.button("Sincronizar status com o cronograma"):
            wbs_service.sync_status_from_tasks()
            st.success("Status atualizado.")
            st.rerun()
