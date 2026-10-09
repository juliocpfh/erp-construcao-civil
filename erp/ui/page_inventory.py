"""Almoxarifado inteligente: saldo, alerta de Lead Time (piscante), consumo diário e recebimento de NF."""
from __future__ import annotations

from datetime import date

import plotly.express as px
import streamlit as st

from erp import db
from erp.services import inventory
from erp.ui.common import blink_alert, can_edit, fmt_num, header, read_only_notice, username


def render() -> None:
    header("Almoxarifado Inteligente e Logística", "NF aprovada dá entrada · RDO/consumo diário dá baixa · alerta pelo Lead Time das tarefas críticas.")
    alerts = inventory.lead_time_alerts()
    if alerts.empty:
        st.success("Estoque cobre o lead time das próximas tarefas críticas.", icon=":material/check_circle:")
    for r in alerts.itertuples():
        blink_alert(f"🔴 RUPTURA PREVISTA: {r.material}",
                    f"Saldo {fmt_num(r.stock)} {r.unit} < necessidade {fmt_num(r.required)} {r.unit} das tarefas críticas "
                    f"{r.tasks} (início {r.first_need:%d/%m/%Y}). Lead time {r.lead_time_days} dias — faltam "
                    f"{fmt_num(r.shortfall)} {r.unit}. Comprar HOJE.")

    tabs = st.tabs(["📦 Saldo", "🧾 Consumo diário", "🚚 Recebimento de NF", "📜 Movimentações"])
    with tabs[0]:
        levels = inventory.stock_levels()
        levels["Situação"] = levels.apply(
            lambda r: "🔴 Ruptura no lead time" if r["id"] in set(alerts.get("material_id", []))
            else ("🟠 Abaixo do mínimo" if r["stock"] < r["min_stock"] else "🟢 OK"), axis=1)
        st.dataframe(levels.rename(columns={"code": "Código", "name": "Material", "unit": "Un", "stock": "Saldo",
                                            "min_stock": "Mínimo", "lead_time_days": "Lead time (d)",
                                            "unit_cost": "Custo un."}).drop(columns=["id"]),
                     hide_index=True, width="stretch", column_config={"Custo un.": st.column_config.NumberColumn(format="R$ %.2f")})
        levels["Valor em estoque"] = levels["stock"].clip(lower=0) * levels["unit_cost"]
        fig = px.bar(levels.sort_values("Valor em estoque", ascending=False).head(12), x="name", y="Valor em estoque",
                     labels={"name": ""})
        fig.update_layout(height=320, margin={"l": 10, "r": 10, "t": 10, "b": 10})
        st.plotly_chart(fig, width="stretch")

    with tabs[1]:
        if not can_edit():
            read_only_notice()
        else:
            _consumption()

    with tabs[2]:
        pending = db.query("SELECT * FROM invoices WHERE status = 'Pendente' AND kind != 'Serviço' ORDER BY issue_date")
        if not pending:
            st.info("Nenhuma NF de material aguardando recebimento.")
        for inv in pending:
            items = db.query_df("SELECT m.name AS Material, ii.quantity AS Quantidade, m.unit AS Un FROM invoice_items ii "
                                "JOIN materials m ON m.id = ii.material_id WHERE invoice_id = ?", (inv["id"],))
            with st.container(border=True):
                st.markdown(f"**NF {inv['number']} · {inv['supplier_name']}** — {inv['issue_date']}")
                st.dataframe(items, hide_index=True, width="stretch")
                if can_edit() and st.button("Conferir e dar entrada no estoque", key=f"rec_{inv['id']}", type="primary"):
                    inventory.approve_invoice(inv["id"], username())
                    st.success("Entrada registrada (NF aprovada e somada ao Custo Real).")
                    st.rerun()

    with tabs[3]:
        mov = db.query_df("SELECT s.date AS Data, m.name AS Material, s.quantity AS Quantidade, m.unit AS Un, s.kind AS Tipo, "
                          "s.source AS Origem, s.notes AS Observação, s.created_by AS Usuário FROM stock_movements s "
                          "JOIN materials m ON m.id = s.material_id ORDER BY s.date DESC, s.id DESC LIMIT 1500")
        mats = st.multiselect("Material", sorted(mov["Material"].unique()))
        if mats:
            mov = mov[mov["Material"].isin(mats)]
        st.dataframe(mov, hide_index=True, width="stretch", height=460)


def _consumption() -> None:
    materials = db.query("SELECT id, code, name, unit FROM materials ORDER BY name")
    with st.form("consumo", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        day = c1.date_input("Data", date.today(), format="DD/MM/YYYY")
        names = {f"{m['code']} · {m['name']} ({m['unit']})": m["id"] for m in materials}
        mat = c2.selectbox("Material", list(names))
        qty = c3.number_input("Quantidade consumida", 0.0, 1e7, step=1.0)
        tasks = {f"{t['code']} · {t['name']}": t["code"] for t in db.query("SELECT code, name FROM tasks WHERE progress < 100 ORDER BY code")}
        task = st.selectbox("Aplicado na tarefa", ["-"] + list(tasks))
        if st.form_submit_button("Registrar baixa", type="primary"):
            rdo = db.query_one("SELECT id FROM rdo WHERE date = ?", (day.isoformat(),))
            try:
                inventory.register_consumption(names[mat], qty, day, rdo["id"] if rdo else None,
                                               f"Consumo diário {tasks.get(task, '')}".strip(), username())
                st.success(f"Baixa registrada{' e vinculada ao RDO do dia' if rdo else ''}. Saldo atual: "
                           f"{fmt_num(inventory.material_stock(names[mat]), 2)}")
            except ValueError as exc:
                st.error(str(exc))
    today = db.query_df("SELECT m.name AS Material, -SUM(s.quantity) AS Consumido, m.unit AS Un FROM stock_movements s "
                        "JOIN materials m ON m.id = s.material_id WHERE s.kind = 'SAIDA' AND s.date = ? GROUP BY m.id",
                        (date.today().isoformat(),))
    st.markdown("**Consumo de hoje**")
    st.dataframe(today, hide_index=True, width="stretch")
