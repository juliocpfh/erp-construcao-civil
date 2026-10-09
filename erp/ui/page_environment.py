"""Proteção à Araucária (checklist de raio de tronco e copa) e Repositório Legal categorizado."""
from __future__ import annotations

from datetime import date

import plotly.graph_objects as go
import streamlit as st

from erp import auth, db
from erp.config import LEGAL_CATEGORIES
from erp.services import environment
from erp.storage import load_media, store_media
from erp.ui.common import blink_alert, can_edit, current_user, header, read_only_notice


def _radius_figure(trees: list[dict]) -> go.Figure:
    fig = go.Figure()
    for i, t in enumerate(trees):
        cx = i * 25
        r = environment.protection_radius(t["dap_cm"], t["crown_radius_m"])
        fig.add_shape(type="circle", x0=cx - r, x1=cx + r, y0=-r, y1=r, line={"color": "#C0392B", "dash": "dash"},
                      fillcolor="rgba(192,57,43,.08)")
        cr = t["crown_radius_m"]
        fig.add_shape(type="circle", x0=cx - cr, x1=cx + cr, y0=-cr, y1=cr, line={"color": "#1E8449"},
                      fillcolor="rgba(30,132,73,.25)")
        fig.add_trace(go.Scatter(x=[cx], y=[0], mode="markers+text", text=[f"{t['tag']}<br>R={r:.1f} m"],
                                 textposition="bottom center", marker={"size": max(t["dap_cm"] / 5, 6), "color": "#6E2C00"},
                                 showlegend=False))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, scaleanchor="x")
    fig.update_layout(height=300, margin={"l": 10, "r": 10, "t": 10, "b": 10})
    return fig


def render() -> None:
    header("Proteção à Araucária e Repositório Legal",
           "Checklist ambiental por exemplar: violação no RDO dispara ALERTA VERMELHO de risco de embargo.")
    tabs = st.tabs(["🌲 Araucárias", "🔎 Inspeções", "⚖️ Repositório Legal"])
    alerts = environment.active_embargo_alerts()
    with tabs[0]:
        for a in alerts:
            blink_alert(f"🚨 ALERTA VERMELHO — RISCO DE EMBARGO · {a['tag']} ({a['date']})", a["violations"])
            if auth.is_admin(current_user()) and st.button("Marcar como regularizado", key=f"res_{a['id']}"):
                environment.resolve_alert(a["id"])
                st.rerun()
        if not alerts:
            st.success("Nenhuma não conformidade ambiental ativa.", icon=":material/park:")
        trees = db.query("SELECT * FROM araucaria_trees ORDER BY tag")
        st.plotly_chart(_radius_figure(trees), width="stretch")
        st.caption("Verde = projeção da copa · vermelho tracejado = raio de proteção = máx(copa; 12 × DAP). "
                   "Nenhuma escavação, tráfego, depósito ou poda dentro do raio sem autorização do órgão ambiental.")
        for t in trees:
            r = environment.protection_radius(t["dap_cm"], t["crown_radius_m"])
            st.markdown(f"- **{t['tag']}** · DAP {t['dap_cm']:.0f} cm · copa {t['crown_radius_m']:.1f} m · "
                        f"**raio de proteção {r:.1f} m** · {t['location']}")
        if can_edit():
            with st.expander("➕ Cadastrar exemplar"):
                with st.form("tree_new", clear_on_submit=True):
                    c = st.columns(3)
                    tag = c[0].text_input("Identificação (ex.: ARA-04)")
                    dap = c[1].number_input("DAP (cm)", 5.0, 300.0, 40.0)
                    crown = c[2].number_input("Raio da copa (m)", 0.5, 30.0, 4.0)
                    loc = st.text_input("Localização")
                    if st.form_submit_button("Cadastrar") and tag:
                        db.execute("INSERT INTO araucaria_trees(tag, dap_cm, crown_radius_m, location) VALUES (?,?,?,?)",
                                   (tag.upper(), dap, crown, loc))
                        st.rerun()

    with tabs[1]:
        if can_edit():
            trees = {t["tag"]: t for t in db.query("SELECT * FROM araucaria_trees ORDER BY tag")}
            with st.form("insp_new"):
                st.markdown("##### Checklist de conformidade (inspeção avulsa)")
                c = st.columns(3)
                tag = c[0].selectbox("Exemplar", list(trees))
                day = c[1].date_input("Data", date.today(), format="DD/MM/YYYY")
                dist = c[2].number_input("Distância da intervenção ao tronco (m)", 0.0, 100.0, 10.0)
                flags = {k: st.checkbox(label, value=(k == "fence_ok")) for k, label in environment.CHECKLIST.items()}
                notes = st.text_input("Observações")
                if st.form_submit_button("Registrar inspeção", type="primary"):
                    rdo = db.query_one("SELECT id FROM rdo WHERE date = ?", (day.isoformat(),))
                    ok, viol = environment.record_inspection(rdo["id"] if rdo else None, trees[tag]["id"], day, dist,
                                                             flags["fence_ok"], flags["crown_damage"], flags["root_damage"],
                                                             flags["soil_compaction"], flags["material_stockpile"], notes)
                    if ok:
                        st.success("Conforme.")
                    else:
                        blink_alert("🚨 ALERTA VERMELHO — RISCO DE EMBARGO", "; ".join(viol))
        else:
            read_only_notice()
        df = db.query_df("SELECT i.date AS Data, t.tag AS Exemplar, i.intervention_distance_m AS 'Distância (m)', "
                         "CASE i.compliant WHEN 1 THEN '✅ Conforme' ELSE '🚨 Violação' END AS Situação, "
                         "i.violations AS Violações, i.notes AS Observações, "
                         "CASE i.resolved WHEN 1 THEN 'Sim' ELSE '' END AS Regularizado "
                         "FROM araucaria_inspections i JOIN araucaria_trees t ON t.id = i.tree_id ORDER BY i.date DESC")
        only = st.toggle("Somente não conformidades")
        if only:
            df = df[df["Situação"].str.contains("Violação")]
        st.dataframe(df, hide_index=True, width="stretch", height=420)

    with tabs[2]:
        allowed = auth.doc_areas(current_user())
        cats = [c for c in LEGAL_CATEGORIES if f"legal:{c}" in allowed]
        if len(cats) < len(LEGAL_CATEGORIES):
            st.caption("🔒 Você vê apenas as categorias liberadas para o seu usuário" + (": " + ", ".join(cats) if cats else "."))
        cat = (st.segmented_control("Categoria", ["Todas"] + cats, default="Todas") or "Todas") if cats else None
        docs = [d for d in db.query("SELECT * FROM legal_docs ORDER BY category, title")
                if d["category"] in cats and cat in ("Todas", d["category"])] if cats else []
        for d in docs:
            with st.container(border=True):
                c1, c2 = st.columns([4, 1])
                c1.markdown(f"**[{d['category']}] {d['title']}**  \n{d['reference'] or ''} · {d['description'] or ''}")
                data = load_media(d["media_key"])
                if data:
                    c2.download_button("PDF", data, file_name=d["filename"] or "documento.pdf", mime="application/pdf",
                                       key=f"leg_{d['id']}")
        if can_edit() and cats:
            with st.form("legal_up", clear_on_submit=True):
                st.markdown("##### ➕ Adicionar lei/norma (PDF)")
                c = st.columns(2)
                category = c[0].selectbox("Categoria", cats)
                ref = c[1].text_input("Referência (ex.: NBR 9050:2020)")
                title = st.text_input("Título")
                f = st.file_uploader("Arquivo PDF", type=["pdf"])
                if st.form_submit_button("Enviar") and f and title:
                    r = store_media(f.getvalue(), f.name, f"legislacao-{category}")
                    db.execute("INSERT INTO legal_docs(category, title, reference, description, media_key, filename, uploaded_at) "
                               "VALUES (?,?,?,?,?,?,?)", (category, title, ref, "Enviado pelo usuário", r.key, f.name, db.now_iso()))
                    st.success("Documento arquivado.")
                    st.rerun()
