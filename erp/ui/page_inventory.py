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

    tabs = st.tabs(["📦 Saldo", "🧾 Consumo diário", "🚚 Recebimento de NF", "📜 Movimentações", "🧱 Cadastro de materiais"])
    with tabs[0]:
        _balance(alerts)
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
    with tabs[4]:
        if not can_edit():
            read_only_notice()
        else:
            _materials_form()


def _balance(alerts) -> None:
    levels = inventory.stock_levels()
    if levels.empty:
        st.info("Nenhum material cadastrado ainda. Use a aba **🧱 Cadastro de materiais**.")
        return
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


def _materials_form() -> None:
    mats = db.query("SELECT * FROM materials ORDER BY code")
    by_label = {f"{m['code']} · {m['name']}": m for m in mats}
    sel = st.selectbox("Material", ["➕ Novo material"] + list(by_label))
    m = by_label.get(sel, {})
    with st.form(f"mat_{m.get('id', 'novo')}", clear_on_submit=not m):
        c1, c2, c3 = st.columns([1, 3, 1])
        code = c1.text_input("Código", m.get("code") or f"M{len(mats) + 1:02d}", disabled=bool(m))
        name = c2.text_input("Descrição", m.get("name", ""))
        unit = c3.text_input("Unidade", m.get("unit", "un"))
        c1, c2, c3 = st.columns(3)
        cost = c1.number_input("Custo unitário (R$)", 0.0, 1e9, float(m.get("unit_cost", 0.0)), step=1.0)
        lead = c2.number_input("Lead time (dias)", 0, 365, int(m.get("lead_time_days", 7)))
        min_stock = c3.number_input("Estoque mínimo", 0.0, 1e9, float(m.get("min_stock", 0.0)))
        initial = 0.0 if m else st.number_input("Saldo inicial (inventário de abertura)", 0.0, 1e9, 0.0)
        if st.form_submit_button("Salvar material", type="primary"):
            if not name.strip() or not unit.strip():
                st.error("Descrição e unidade são obrigatórias.")
            elif m:
                db.execute("UPDATE materials SET name = ?, unit = ?, unit_cost = ?, lead_time_days = ?, min_stock = ? "
                           "WHERE id = ?", (name.strip(), unit.strip(), cost, int(lead), min_stock, m["id"]))
                st.success("Material atualizado.")
                st.rerun()
            elif db.query_one("SELECT id FROM materials WHERE code = ?", (code.strip().upper(),)):
                st.error("Já existe material com esse código.")
            else:
                mid = db.execute("INSERT INTO materials(code, name, unit, unit_cost, lead_time_days, min_stock) "
                                 "VALUES (?,?,?,?,?,?)", (code.strip().upper(), name.strip(), unit.strip(), cost,
                                                          int(lead), min_stock))
                if initial:
                    inventory.add_movement(mid, initial, date.today(), "ENTRADA", "Inventário inicial",
                                           user=username())
                st.success("Material cadastrado.")
                st.rerun()


def _consumption() -> None:
    materials = db.query("SELECT id, code, name, unit FROM materials ORDER BY name")
    if not materials:
        st.info("Cadastre os materiais na aba **🧱 Cadastro de materiais** antes de registrar consumo.")
        return
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
