"""Painel Executivo: indicadores PMI, alertas e Curva S."""
from __future__ import annotations

from datetime import date

import streamlit as st

from erp.services.analytics import collect_report_data
from erp.services.evm import performance_label
from erp.services.project import project_info
from erp.ui import charts
from erp.ui.common import (
    blink_alert, empty_project_guide, fmt_num, has_schedule, header, money, money_short, username,
)


def render() -> None:
    info = project_info()
    sub = " · ".join(x for x in (info["location"], info["description"], f"Data de status {date.today():%d/%m/%Y}") if x)
    header(f"🏗️ {info['name']}", sub)
    if not has_schedule():
        empty_project_guide()
        return
    data = collect_report_data(user=username())
    evm, summary = data["evm"], data["summary"]

    for a in data["embargo_alerts"]:
        blink_alert(f"🚨 ALERTA VERMELHO — RISCO DE EMBARGO AMBIENTAL (Araucária {a['tag']})",
                    f"{a['date']}: {a['violations']}")
    stock = data["stock_alerts"]
    if not stock.empty:
        for r in stock.itertuples():
            blink_alert(f"📦 Estoque insuficiente para o Lead Time: {r.material}",
                        f"Saldo {fmt_num(r.stock)} {r.unit} · necessário {fmt_num(r.required)} {r.unit} para {r.tasks} "
                        f"(lead time {r.lead_time_days} dias) — emitir pedido hoje.", level="warning")

    c = st.columns(4)
    c[0].metric("Avanço físico", f"{evm['pct_earned']:.1f}%", f"{evm['pct_earned'] - evm['pct_planned']:+.1f} p.p. vs planejado")
    c[1].metric("IDC (CPI)", f"{evm['IDC']:.3f}", performance_label(evm["IDC"]),
                delta_color="green" if evm["IDC"] >= 1 else ("orange" if evm["IDC"] >= 0.9 else "red"), delta_arrow="off")
    c[2].metric("IDP (SPI)", f"{evm['IDP']:.3f}", performance_label(evm["IDP"]),
                delta_color="green" if evm["IDP"] >= 1 else ("orange" if evm["IDP"] >= 0.9 else "red"), delta_arrow="off")
    c[3].metric("Término projetado", f"{summary['projected_finish']:%d/%m/%Y}",
                f"{summary['delay_days']:+d} dias vs baseline", delta_color="inverse")
    c = st.columns(4)
    c[0].metric("VP · Planejado", money_short(evm["VP"]), help=money(evm["VP"]))
    c[1].metric("VA · Agregado", money_short(evm["VA"]), help=money(evm["VA"]))
    c[2].metric("CR · Custo Real", money_short(evm["CR"]), money_short(evm["VC"]) + " (VA-CR)",
                delta_color="normal", help=money(evm["CR"]))
    c[3].metric("EAC · Estimativa no término", money_short(evm["EAC"]), f"Orçamento {money_short(evm['BAC'])}",
                delta_color="off", delta_arrow="off", help=money(evm["EAC"]))

    left, right = st.columns([2, 1])
    with left:
        st.subheader("Curva S — VP x VA x CR")
        st.plotly_chart(charts.s_curve(data["curve"]), width="stretch")
    with right:
        st.plotly_chart(charts.index_gauge(evm["IDC"], "IDC (custo)"), width="stretch")
        st.plotly_chart(charts.index_gauge(evm["IDP"], "IDP (prazo)"), width="stretch")

    st.subheader("Próximas tarefas críticas")
    crit = data["critical"].head(8)
    st.dataframe(
        crit[["code", "name", "start", "finish", "baseline_finish", "finish_variance", "progress"]].rename(columns={
            "code": "Código", "name": "Tarefa", "start": "Início", "finish": "Término projetado",
            "baseline_finish": "Término baseline", "finish_variance": "Desvio (dias)", "progress": "Avanço %"}),
        hide_index=True, width="stretch",
        column_config={"Avanço %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%")},
    )
