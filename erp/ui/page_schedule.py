"""Cronograma: Gantt interativo com Caminho Crítico (CPM) e painel Baseline x Real."""
from __future__ import annotations

from datetime import date

import streamlit as st

from erp import db
from erp.services import scheduling
from erp.ui import charts
from erp.ui.common import can_edit, header, money, money_short, read_only_notice


def render() -> None:
    header("Cronograma, CPM e Baseline x Real",
           "Caminho crítico em VERMELHO. O cronograma é recalculado automaticamente a cada RDO (chuva forte/ocorrências).")
    today = date.today()
    sched = scheduling.compute_schedule(today)
    summary = scheduling.project_summary(today, sched)

    c = st.columns(4)
    c[0].metric("Término baseline", f"{summary['baseline_finish']:%d/%m/%Y}")
    c[1].metric("Término projetado", f"{summary['projected_finish']:%d/%m/%Y}", f"{summary['delay_days']:+d} dias",
                delta_color="inverse")
    c[2].metric("Dias de impacto (RDO)", summary["impact_days"])
    c[3].metric("Custo do atraso (indiretos)", money_short(summary["delay_cost"]), help=money(summary["delay_cost"]))

    tab_gantt, tab_cpm, tab_base, tab_imp, tab_edit = st.tabs(
        ["📊 Gantt CPM", "🧮 Tabela CPM", "💸 Baseline x Real", "🌧️ Impactos do RDO", "✏️ Tarefas"])

    with tab_gantt:
        c1, c2, c3 = st.columns(3)
        show_base = c1.toggle("Mostrar baseline (contorno cinza)", value=True)
        only_open = c2.toggle("Ocultar tarefas concluídas", value=False)
        compact = c3.toggle("Rótulos compactos (celular)", value=False)
        view = sched[sched["progress"] < 100] if only_open else sched
        st.plotly_chart(charts.gantt(view, show_base, today, compact=compact), width="stretch")

    with tab_cpm:
        st.caption("ES/EF/LS/LF em dias desde o início da obra. Folga total = LS − ES; folga zero = crítica.")
        st.dataframe(
            sched[["code", "name", "eff_duration", "predecessors", "es", "ef", "ls", "lf", "slack", "critical",
                   "start", "finish", "progress"]].rename(columns={
                "code": "Código", "name": "Tarefa", "eff_duration": "Duração (c/ impactos)", "predecessors": "Predecessoras",
                "es": "ES", "ef": "EF", "ls": "LS", "lf": "LF", "slack": "Folga", "critical": "Crítica",
                "start": "Início", "finish": "Término", "progress": "Avanço %"}),
            hide_index=True, width="stretch", height=560,
            column_config={"Avanço %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%")},
        )

    with tab_base:
        df = scheduling.baseline_vs_actual(today, sched)
        lost = df["money_lost"].sum()
        c = st.columns(3)
        c[0].metric("Perda total estimada", money_short(lost), help=money(lost))
        c[1].metric("Sobrecusto (CR > VA)", money_short((-df["cost_variance"]).clip(lower=0).sum()))
        c[2].metric("Dias perdidos em tarefas críticas", int(df.loc[df["critical"], "lost_days"].sum()))
        l, r = st.columns(2)
        with l:
            st.markdown("**Onde se perdeu dinheiro (top 12)**")
            st.plotly_chart(charts.losses_bar(df), width="stretch")
        with r:
            st.markdown("**Prazo x Custo por tarefa iniciada**")
            st.plotly_chart(charts.variance_scatter(df), width="stretch")
        st.dataframe(
            df.sort_values("money_lost", ascending=False).rename(columns={
                "code": "Código", "name": "Tarefa", "wbs_name": "Entrega", "critical": "Crítica",
                "baseline_start": "Início BL", "baseline_finish": "Fim BL", "start": "Início real/proj.",
                "finish": "Fim real/proj.", "finish_variance": "Desvio fim (d)", "delay": "Impactos RDO (d)",
                "lost_days": "Dias perdidos", "baseline_cost": "Orçado", "progress": "Avanço %",
                "earned_value": "VA", "actual_cost": "CR", "cost_variance": "VA-CR", "delay_cost": "Custo atraso",
                "money_lost": "Perda"}).drop(columns=["id"]),
            hide_index=True, width="stretch",
            column_config={k: st.column_config.NumberColumn(format="R$ %.2f")
                           for k in ("Orçado", "VA", "CR", "VA-CR", "Custo atraso", "Perda")},
        )

    with tab_imp:
        imp = db.query_df(
            "SELECT i.created_at AS registrado, r.date AS rdo, t.code AS tarefa, i.days AS dias, i.reason AS motivo "
            "FROM schedule_impacts i JOIN tasks t ON t.id = i.task_id LEFT JOIN rdo r ON r.id = i.rdo_id "
            "ORDER BY i.id DESC")
        st.dataframe(imp, hide_index=True, width="stretch")

    with tab_edit:
        if not can_edit():
            read_only_notice()
        else:
            _task_editor(sched)


def _task_editor(sched) -> None:
    st.markdown("##### Editar duração / tipo de exposição")
    options = {f"{r.code} · {r.name}": int(r.id) for r in sched.itertuples()}
    sel = st.selectbox("Tarefa", list(options))
    row = sched[sched["id"] == options[sel]].iloc[0]
    with st.form("task_edit"):
        dur = st.number_input("Duração planejada (dias)", 1, 400, int(row["duration"]))
        outdoor = st.checkbox("Tarefa externa (sofre impacto de Chuva Forte)", bool(row["outdoor"]))
        rebase = st.checkbox("Atualizar também a baseline (re-baseline aprovado)", False)
        if st.form_submit_button("Salvar", type="primary"):
            db.execute("UPDATE tasks SET duration = ?, outdoor = ? WHERE id = ?", (int(dur), int(outdoor), options[sel]))
            if rebase:
                scheduling.freeze_baseline()
            st.success("Tarefa atualizada — cronograma recalculado.")
            st.rerun()

    st.markdown("##### Nova tarefa")
    wbs = {f"{w['code']} · {w['name']}": w["id"] for w in db.query("SELECT id, code, name FROM wbs ORDER BY id")}
    with st.form("task_new", clear_on_submit=True):
        c1, c2 = st.columns(2)
        code = c1.text_input("Código (ex.: X01)")
        name = c2.text_input("Nome")
        c1, c2, c3 = st.columns(3)
        dur = c1.number_input("Duração (dias)", 1, 400, 10)
        cost = c2.number_input("Custo orçado (R$)", 0.0, 1e9, 50000.0, step=1000.0)
        outdoor = c3.checkbox("Externa")
        w = st.selectbox("Entrega (EAP)", list(wbs))
        preds = st.multiselect("Predecessoras", list(options))
        if st.form_submit_button("Incluir tarefa"):
            if not code or not name:
                st.error("Código e nome são obrigatórios.")
            else:
                tid = db.execute("INSERT INTO tasks(code, name, wbs_id, duration, outdoor, baseline_cost) VALUES (?,?,?,?,?,?)",
                                 (code.strip().upper(), name.strip(), wbs[w], int(dur), int(outdoor), cost))
                for p in preds:
                    db.execute("INSERT INTO task_deps(task_id, predecessor_id) VALUES (?,?)", (tid, options[p]))
                try:
                    scheduling.compute_schedule()
                except ValueError as exc:
                    db.execute("DELETE FROM tasks WHERE id = ?", (tid,))
                    st.error(str(exc))
                else:
                    db.execute("UPDATE tasks SET baseline_start = ?, baseline_finish = ? WHERE id = ?",
                               (*_new_task_baseline(tid), tid))
                    st.success("Tarefa incluída.")
                    st.rerun()


def _new_task_baseline(tid: int) -> tuple[str, str]:
    s = scheduling.compute_schedule()
    row = s[s["id"] == tid].iloc[0]
    return row["start"].isoformat(), row["finish"].isoformat()
