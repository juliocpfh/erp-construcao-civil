"""Tributos, BDI, cotações e custos (EVM). O lançamento e a aprovação de NFs ficam em page_nfs."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from erp import db
from erp.services import evm, finance
from erp.ui import charts
from erp.ui.common import blink_alert, can_edit, header, money, money_short
from erp.ui.page_nfs import KINDS


def render() -> None:
    header("Tributos, BDI & Custos", "Composição do BDI, cotações e custos (EVM). NFs ficam em Gestão de NFs.")
    tabs = st.tabs(["🧮 BDI & Tributos", "📨 Cotações", "📈 Custos (PMI)"])
    with tabs[0]:
        _bdi()
    with tabs[1]:
        _quotes()
    with tabs[2]:
        _costs()

def _bdi() -> None:
    p = finance.load_bdi_params()
    with st.form("bdi"):
        st.markdown("**Composição do BDI** (Acórdão TCU 2.622/2013)")
        c = st.columns(3)
        p.administracao_central = c[0].number_input("Administração central (%)", 0.0, 30.0, p.administracao_central, 0.1)
        p.seguro = c[1].number_input("Seguro (%)", 0.0, 10.0, p.seguro, 0.05)
        p.risco = c[2].number_input("Risco (%)", 0.0, 10.0, p.risco, 0.05)
        c = st.columns(3)
        p.garantia = c[0].number_input("Garantia (%)", 0.0, 10.0, p.garantia, 0.05)
        p.despesas_financeiras = c[1].number_input("Despesas financeiras (%)", 0.0, 10.0, p.despesas_financeiras, 0.05)
        p.lucro = c[2].number_input("Lucro (%)", 0.0, 30.0, p.lucro, 0.1)
        st.markdown("**Tributos sobre o faturamento (separados do BDI)**")
        c = st.columns(4)
        p.pis = c[0].number_input("PIS (%)", 0.0, 5.0, p.pis, 0.05)
        p.cofins = c[1].number_input("COFINS (%)", 0.0, 10.0, p.cofins, 0.05)
        p.iss = c[2].number_input("ISS (%)", 0.0, 5.0, p.iss, 0.05)
        p.cprb = c[3].number_input("INSS/CPRB (%)", 0.0, 10.0, p.cprb, 0.05)
        st.markdown("**Benefícios fiscais**")
        c = st.columns([1, 2])
        p.reducao_beneficio = c[0].number_input("Redução da carga tributária (%)", 0.0, 100.0, p.reducao_beneficio, 1.0)
        p.beneficios_fiscais = c[1].text_input("Descrição dos benefícios", p.beneficios_fiscais,
                                               placeholder="Ex.: redução de base de cálculo do ISS (dedução de materiais)")
        save = st.form_submit_button("Calcular e salvar", type="primary", disabled=not can_edit())
    if save:
        finance.save_bdi_params(p)
    r = finance.compute_bdi(p)
    c = st.columns(4)
    c[0].metric("BDI total", f"{r['bdi']:.2f}%")
    c[1].metric("BDI sem tributos", f"{r['bdi_sem_tributos']:.2f}%")
    c[2].metric("Parcela de tributos", f"{r['parcela_tributos']:.2f} p.p.")
    c[3].metric("Economia com benefício", f"{r['economia_beneficio']:.2f} p.p.")
    df = pd.DataFrame({"Componente": ["Adm. central", "Seguro", "Risco", "Garantia", "Desp. financeiras", "Lucro"] + list(r["tributos"]),
                       "Valor %": [p.administracao_central, p.seguro, p.risco, p.garantia, p.despesas_financeiras, p.lucro]
                       + list(r["tributos"].values()),
                       "Grupo": ["Despesas indiretas"] * 5 + ["Lucro"] + ["Tributos"] * len(r["tributos"])})
    fig = px.bar(df, x="Valor %", y="Componente", color="Grupo", orientation="h",
                 color_discrete_map={"Despesas indiretas": "#2E86C1", "Lucro": "#1E8449", "Tributos": "#C0392B"})
    fig.update_layout(height=360, margin={"l": 10, "r": 10, "t": 10, "b": 10})
    st.plotly_chart(fig, width="stretch")
    direct = st.number_input("Simular preço de venda — custo direto (R$)", 0.0, 1e10, 1_000_000.0, step=10000.0)
    st.write(f"Preço com BDI: **{money(finance.price_with_bdi(direct, r['bdi']))}**")


def _quotes() -> None:
    df = db.query("SELECT * FROM quotes ORDER BY created_at DESC")
    for q in df:
        alerts = finance.quote_alerts(q["kind"], bool(q["iss_highlighted"]), bool(q["inss_highlighted"]))
        with st.container(border=True):
            c1, c2 = st.columns([2, 1])
            c1.markdown(f"**{q['supplier']}** — {q['description']}  \n{q['kind']} · "
                        f"ISS {'destacado ✅' if q['iss_highlighted'] else 'NÃO destacado'} · "
                        f"INSS {'destacado ✅' if q['inss_highlighted'] else 'NÃO destacado'}")
            c2.metric("Valor", money(q["value"]))
            for a in alerts:
                blink_alert("⚠️ " + a, level="warning", blink=True)
    if not can_edit():
        return
    with st.form("quote_new", clear_on_submit=True):
        st.markdown("##### Nova cotação")
        c1, c2 = st.columns(2)
        sup = c1.text_input("Fornecedor")
        kind = c2.selectbox("Tipo", KINDS)
        desc = st.text_input("Descrição")
        c1, c2, c3 = st.columns(3)
        val = c1.number_input("Valor (R$)", 0.0, 1e10, step=1000.0)
        iss_h = c2.checkbox("Proposta destaca ISS")
        inss_h = c3.checkbox("Proposta destaca retenção de INSS")
        if st.form_submit_button("Registrar cotação"):
            db.execute("INSERT INTO quotes(supplier, description, kind, value, iss_highlighted, inss_highlighted, created_at) "
                       "VALUES (?,?,?,?,?,?,?)", (sup, desc, kind, val, int(iss_h), int(inss_h), db.now_iso()))
            for a in finance.quote_alerts(kind, iss_h, inss_h):
                st.warning(a)
            st.rerun()


def _costs() -> None:
    snap = evm.evm_snapshot()
    c = st.columns(5)
    c[0].metric("VP", money_short(snap["VP"]), help=money(snap["VP"]))
    c[1].metric("VA", money_short(snap["VA"]), help=money(snap["VA"]))
    c[2].metric("CR", money_short(snap["CR"]), help=money(snap["CR"]))
    c[3].metric("IDC", f"{snap['IDC']:.3f}")
    c[4].metric("IDP", f"{snap['IDP']:.3f}")
    st.plotly_chart(charts.s_curve(evm.s_curve()), width="stretch")
    by_task = db.query_df("SELECT t.code AS Tarefa, t.name AS Descrição, t.baseline_cost AS Orçado, "
                          "t.baseline_cost * t.progress / 100 AS VA, COALESCE(SUM(i.total_value), 0) AS CR "
                          "FROM tasks t LEFT JOIN invoices i ON i.task_id = t.id AND i.status = 'Aprovada' "
                          "GROUP BY t.id ORDER BY t.code")
    by_task["IDC"] = (by_task["VA"] / by_task["CR"].where(by_task["CR"] > 0)).round(3)
    st.dataframe(by_task, hide_index=True, width="stretch",
                 column_config={k: st.column_config.NumberColumn(format="R$ %.2f") for k in ("Orçado", "VA", "CR")})
