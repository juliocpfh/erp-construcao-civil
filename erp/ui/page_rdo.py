"""Diário de Obra (RDO) com recálculo do cronograma em tempo real."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from erp import db
from erp.config import HEAVY_RAIN, WEATHER_OPTIONS
from erp.services import environment, scheduling
from erp.services.rdo import RDOInput, save_rdo
from erp.storage import store_media
from erp.ui import charts
from erp.ui.common import blink_alert, can_edit, header, read_only_notice, username

DEFAULT_LABOR = ["Mestre de obras", "Pedreiro", "Servente", "Carpinteiro", "Armador", "Eletricista", "Encanador",
                 "Técnico de segurança"]


def render() -> None:
    header("Diário de Obra (RDO)", "Clima, mão de obra, ocorrências, avanço físico, consumo e conformidade ambiental.")
    tab_new, tab_hist, tab_stats = st.tabs(["📝 Novo RDO", "📚 Histórico", "📈 Clima & Efetivo"])
    with tab_new:
        if can_edit():
            _new_rdo()
        else:
            read_only_notice()
    with tab_hist:
        _history()
    with tab_stats:
        rdo = db.query_df("SELECT date, weather FROM rdo")
        if not rdo.empty:
            st.plotly_chart(charts.weather_bar(rdo), width="stretch")
        labor = db.query_df("SELECT r.date, SUM(l.quantity) AS efetivo FROM rdo r JOIN rdo_labor l ON l.rdo_id = r.id "
                            "GROUP BY r.date ORDER BY r.date")
        if not labor.empty:
            st.markdown("**Efetivo diário em campo**")
            st.area_chart(labor.set_index("date"), height=240)


def _new_rdo() -> None:
    c1, c2, c3 = st.columns(3)
    day = c1.date_input("Data do RDO", date.today(), format="DD/MM/YYYY")
    weather = c2.selectbox("Clima", WEATHER_OPTIONS, index=0)
    exists = db.query_one("SELECT id FROM rdo WHERE date = ?", (day.isoformat(),))
    if exists:
        st.warning(f"Já existe RDO para {day:%d/%m/%Y}. Escolha outra data ou consulte o histórico.")

    sched = scheduling.compute_schedule(day)
    active = scheduling.active_tasks_on(day, sched)
    task_opts = {f"{r.code} · {r.name}" + (" 🔴" if r.critical else ""): int(r.id) for r in sched[sched["progress"] < 100].itertuples()}
    prob_task = c3.selectbox("Problema em tarefa (opcional)", ["-"] + list(task_opts))
    prob_days = st.slider("Dias de impacto do problema", 0, 15, 0, disabled=prob_task == "-")

    # pré-visualização em tempo real do recálculo
    preview = scheduling.preview_rdo_impact(day, weather, task_opts.get(prob_task), prob_days if prob_task != "-" else 0)
    if preview["impacts"]:
        crit = [i for i in preview["critical_impacts"]]
        msg = (f"Recalculo automático: término projetado {preview['finish_before']:%d/%m/%Y} → "
               f"{preview['finish_after']:%d/%m/%Y} ({preview['shift_days']:+d} dias).")
        detail = "; ".join(i["reason"] for i in preview["impacts"])
        if crit and preview["shift_days"] > 0:
            blink_alert("⛈️ Impacto em tarefa CRÍTICA — " + msg, detail)
        else:
            blink_alert("🌧️ " + msg, detail + " (sem efeito na data final: há folga)", level="warning", blink=False)
    elif weather == HEAVY_RAIN:
        st.info("Chuva Forte registrada, mas não há tarefas externas ativas nesta data: sem impacto no prazo.")

    trees = db.query("SELECT * FROM araucaria_trees ORDER BY tag")
    contacts = {c["name"]: c["id"] for c in db.query("SELECT id, name FROM contacts WHERE category = 'Equipe' ORDER BY name")}
    materials = db.query("SELECT id, code, name, unit FROM materials ORDER BY name")

    with st.form("rdo_form"):
        c1, c2, c3 = st.columns(3)
        temp = c1.number_input("Temperatura (°C)", -5.0, 45.0, 20.0, step=0.5)
        rain = c2.number_input("Precipitação (mm)", 0.0, 300.0, 40.0 if weather == HEAVY_RAIN else 0.0, step=1.0)
        signer = c3.selectbox("Assinado por", list(contacts) or ["-"])

        st.markdown("**👷 Mão de obra**")
        labor = st.data_editor(pd.DataFrame({"Função": DEFAULT_LABOR, "Quantidade": [1, 6, 6, 4, 3, 0, 0, 1]}),
                               num_rows="dynamic", hide_index=True, key="rdo_labor", width="stretch")

        st.markdown("**📈 Avanço físico das tarefas ativas** (% acumulado)")
        prog_df = pd.DataFrame({
            "id": active["id"].astype(int), "Tarefa": active["code"] + " · " + active["name"],
            "Crítica": active["critical"], "Avanço anterior %": active["progress"].round(1),
            "Avanço atual %": active["progress"].round(1),
        }) if not active.empty else pd.DataFrame(columns=["id", "Tarefa", "Crítica", "Avanço anterior %", "Avanço atual %"])
        prog = st.data_editor(prog_df, hide_index=True, key="rdo_prog", width="stretch",
                              disabled=["id", "Tarefa", "Crítica", "Avanço anterior %"],
                              column_config={"id": None, "Avanço atual %": st.column_config.NumberColumn(min_value=0, max_value=100)})

        st.markdown("**📦 Consumo de materiais (baixa no estoque)**")
        mat_names = [f"{m['code']} · {m['name']} ({m['unit']})" for m in materials]
        cons = st.data_editor(pd.DataFrame({"Material": pd.Series([], dtype="object"), "Quantidade": pd.Series([], dtype="float")}),
                              num_rows="dynamic", hide_index=True, key="rdo_cons", width="stretch",
                              column_config={"Material": st.column_config.SelectboxColumn(options=mat_names)})

        occurrences = st.text_area("Ocorrências do dia", placeholder="Ex.: chuva forte paralisou concretagem da laje...")

        st.markdown("**🌲 Inspeção das Araucárias** (raio de tronco e copa)")
        insp = []
        for t in trees:
            radius = environment.protection_radius(t["dap_cm"], t["crown_radius_m"])
            with st.expander(f"{t['tag']} — raio de proteção {radius:.1f} m ({t['location']})"):
                inspect = st.checkbox("Inspecionar neste RDO", value=True, key=f"insp_on_{t['id']}")
                dist = st.number_input("Distância da intervenção mais próxima ao tronco (m)", 0.0, 100.0,
                                       round(radius + 3, 1), key=f"insp_d_{t['id']}")
                cc = st.columns(2)
                fence = cc[0].checkbox(environment.CHECKLIST["fence_ok"], True, key=f"insp_f_{t['id']}")
                crown = cc[0].checkbox(environment.CHECKLIST["crown_damage"], False, key=f"insp_c_{t['id']}")
                root = cc[1].checkbox(environment.CHECKLIST["root_damage"], False, key=f"insp_r_{t['id']}")
                soil = cc[1].checkbox(environment.CHECKLIST["soil_compaction"], False, key=f"insp_s_{t['id']}")
                stock = cc[1].checkbox(environment.CHECKLIST["material_stockpile"], False, key=f"insp_m_{t['id']}")
                if inspect:
                    insp.append({"tree_id": t["id"], "distance_m": dist, "fence_ok": fence, "crown_damage": crown,
                                 "root_damage": root, "soil_compaction": soil, "material_stockpile": stock})

        st.markdown("**📷 Fotos do dia** (vão para o memorial e o time-lapse)")
        stages = {w["name"]: w["id"] for w in db.query("SELECT id, name FROM wbs WHERE code LIKE '1.%' AND code NOT LIKE '1.%.%' ORDER BY id")}
        stage = st.selectbox("Etapa das fotos", list(stages))
        photos = st.file_uploader("Fotos", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

        submitted = st.form_submit_button("💾 Salvar RDO e recalcular cronograma", type="primary", disabled=bool(exists))

    if not submitted:
        return
    progress = {}
    for r in prog.itertuples():
        if float(r[5]) != float(r[4]):
            progress[int(r.id)] = float(r[5])
    consumption = {}
    for r in cons.dropna().itertuples():
        idx = mat_names.index(r.Material) if r.Material in mat_names else -1
        if idx >= 0 and r.Quantidade:
            consumption[materials[idx]["id"]] = consumption.get(materials[idx]["id"], 0) + float(r.Quantidade)
    labor_map = {str(r["Função"]): int(r["Quantidade"] or 0) for _, r in labor.dropna().iterrows()}
    try:
        result = save_rdo(RDOInput(
            day=day, weather=weather, temperature=temp, rain_mm=rain, occurrences=occurrences, labor=labor_map,
            progress=progress, consumption=consumption, problem_task_id=task_opts.get(prob_task),
            problem_days=prob_days if prob_task != "-" else 0, signed_by_contact_id=contacts.get(signer),
            araucaria=insp, created_by=username()))
    except ValueError as exc:
        st.error(str(exc))
        return
    for f in photos or []:
        res = store_media(f.getvalue(), f.name, "fotos-obra")
        db.execute("INSERT INTO photos(date, wbs_id, caption, media_key, rdo_id) VALUES (?,?,?,?,?)",
                   (day.isoformat(), stages[stage], f"RDO {day:%d/%m/%Y} - {stage}", res.key, result["rdo_id"]))
    st.success(f"RDO de {day:%d/%m/%Y} salvo.")
    if result["impacts"]:
        st.warning(f"Cronograma recalculado: nova data final {result['finish_after']:%d/%m/%Y} "
                   f"({result['shift_days']:+d} dias; {result['delay_vs_baseline']:+d} dias vs baseline).")
    for v in result["embargo_risk"]:
        blink_alert("🚨 ALERTA VERMELHO — RISCO DE EMBARGO", "; ".join(v["violations"]))
    for e in result["consumption_errors"]:
        st.error(e)


def _history() -> None:
    df = db.query_df(
        "SELECT r.id, r.date AS Data, r.weather AS Clima, r.temperature AS 'Temp °C', r.rain_mm AS 'Chuva mm', "
        "(SELECT SUM(quantity) FROM rdo_labor l WHERE l.rdo_id = r.id) AS Efetivo, r.occurrences AS Ocorrências, "
        "t.code AS 'Tarefa c/ problema', r.problem_days AS 'Dias impacto', c.name AS 'Assinado por' "
        "FROM rdo r LEFT JOIN tasks t ON t.id = r.problem_task_id LEFT JOIN contacts c ON c.id = r.signed_by_contact_id "
        "ORDER BY r.date DESC")
    c1, c2 = st.columns(2)
    weather = c1.multiselect("Filtrar clima", WEATHER_OPTIONS)
    text = c2.text_input("Buscar nas ocorrências")
    if weather:
        df = df[df["Clima"].isin(weather)]
    if text:
        df = df[df["Ocorrências"].fillna("").str.contains(text, case=False)]
    st.caption(f"{len(df)} diários")
    st.dataframe(df.drop(columns=["id"]), hide_index=True, width="stretch", height=480)
