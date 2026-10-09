"""Memorial fotográfico, Time-lapse (.mp4 via OpenCV) e Flash Report executivo (PDF)."""
from __future__ import annotations

import time
from datetime import date

import streamlit as st

from erp import db
from erp.config import PROJECT_NAME
from erp.services.analytics import collect_report_data
from erp.services.reports import build_flash_report
from erp.services.timelapse import Frame, build_timelapse
from erp.storage import load_media, store_media
from erp.ui.common import can_edit, header, username


def _stages() -> dict[str, int]:
    return {w["name"]: w["id"] for w in db.query(
        "SELECT DISTINCT w.id, w.name FROM photos p JOIN wbs w ON w.id = p.wbs_id ORDER BY w.code")}


def _frames(wbs_id: int | None = None) -> list[Frame]:
    sql = "SELECT p.date, p.caption, p.media_key, w.name AS stage FROM photos p LEFT JOIN wbs w ON w.id = p.wbs_id"
    rows = db.query(sql + (" WHERE p.wbs_id = ?" if wbs_id else "") + " ORDER BY p.date",
                    (wbs_id,) if wbs_id else ())
    frames = []
    for r in rows:
        data = load_media(r["media_key"])
        if data:
            frames.append(Frame(date.fromisoformat(r["date"]), r["stage"] or r["caption"] or "", data))
    return frames


def render() -> None:
    header("Memorial, Time-lapse e Flash Report", "Vídeo .mp4 gerado com OpenCV e PDF executivo gerado em memória.")
    tabs = st.tabs(["🎬 Time-lapse", "📄 Flash Report (PDF)", "🖼️ Memorial fotográfico"])

    with tabs[0]:
        c1, c2 = st.columns(2)
        fps = c1.slider("Velocidade (quadros/s)", 6, 30, 12)
        hold = c2.slider("Tempo por foto (s)", 0.2, 2.0, 0.5, 0.1)
        b1, b2 = st.columns(2)
        stages = _stages()
        stage = b2.selectbox("Etapa", list(stages), label_visibility="collapsed")
        if b1.button("🎬 Vídeo Geral da Obra", type="primary", width="stretch"):
            _make_video(None, "Vídeo Geral da Obra", fps, hold)
        if b2.button("🎯 Vídeo Filtrado por Etapa", width="stretch"):
            _make_video(stages.get(stage), f"Etapa: {stage}", fps, hold)
        vid = st.session_state.get("timelapse")
        if vid:
            st.video(vid["data"])
            st.caption(f"{vid['title']} · {vid['frames']} fotos · {len(vid['data']) / 1024:.0f} KB · gerado em {vid['secs']:.1f}s")
            st.download_button("⬇️ Baixar .mp4", vid["data"], file_name=vid["file"], mime="video/mp4")

    with tabs[1]:
        st.write("Resumo executivo com IDC/IDP, Curva S, caminho crítico, alertas de estoque/embargo e perdas Baseline x Real.")
        if st.button("📄 Gerar Relatório Executivo (PDF)", type="primary"):
            t0 = time.perf_counter()
            pdf = build_flash_report(collect_report_data(user=username()))
            st.session_state["flash_pdf"] = (pdf, time.perf_counter() - t0)
        if "flash_pdf" in st.session_state:
            pdf, secs = st.session_state["flash_pdf"]
            st.success(f"PDF gerado em memória em {secs * 1000:.0f} ms ({len(pdf) / 1024:.0f} KB).")
            st.download_button("⬇️ Baixar Flash Report", pdf, file_name=f"flash_report_{date.today():%Y%m%d}.pdf",
                               mime="application/pdf", type="primary")

    with tabs[2]:
        if can_edit():
            with st.expander("➕ Enviar fotos para o memorial"):
                all_stages = {w["name"]: w["id"] for w in db.query(
                    "SELECT id, name FROM wbs WHERE code LIKE '1.%' AND code NOT LIKE '1.%.%' ORDER BY id")}
                with st.form("photo_up", clear_on_submit=True):
                    d = st.date_input("Data", date.today(), format="DD/MM/YYYY")
                    s = st.selectbox("Etapa", list(all_stages))
                    cap = st.text_input("Legenda")
                    files = st.file_uploader("Fotos", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
                    if st.form_submit_button("Enviar (S3 + FTP)") and files:
                        for f in files:
                            r = store_media(f.getvalue(), f.name, "fotos-obra")
                            db.execute("INSERT INTO photos(date, wbs_id, caption, media_key) VALUES (?,?,?,?)",
                                       (d.isoformat(), all_stages[s], cap or s, r.key))
                        st.success(f"{len(files)} foto(s) armazenada(s).")
        rows = db.query("SELECT p.date, p.caption, p.media_key, w.name AS stage FROM photos p "
                        "LEFT JOIN wbs w ON w.id = p.wbs_id ORDER BY p.date DESC")
        stage_filter = st.selectbox("Filtrar etapa", ["Todas"] + sorted({r["stage"] for r in rows if r["stage"]}))
        if stage_filter != "Todas":
            rows = [r for r in rows if r["stage"] == stage_filter]
        page_size = 12
        pages = max((len(rows) - 1) // page_size + 1, 1)
        page = st.number_input("Página", 1, pages, 1)
        cols = st.columns(3)
        for i, r in enumerate(rows[(page - 1) * page_size: page * page_size]):
            data = load_media(r["media_key"])
            if data:
                cols[i % 3].image(data, caption=f"{date.fromisoformat(r['date']):%d/%m/%Y} · {r['caption']}", width="stretch")


def _make_video(wbs_id: int | None, title: str, fps: int, hold: float) -> None:
    frames = _frames(wbs_id)
    if not frames:
        st.warning("Não há fotos para esta seleção.")
        return
    with st.spinner(f"Renderizando {len(frames)} fotos com OpenCV..."):
        t0 = time.perf_counter()
        data = build_timelapse(frames, f"{PROJECT_NAME} - {title}", fps=fps, seconds_per_photo=hold)
    slug = "geral" if wbs_id is None else f"etapa_{wbs_id}"
    st.session_state["timelapse"] = {"data": data, "title": title, "frames": len(frames),
                                     "secs": time.perf_counter() - t0, "file": f"timelapse_{slug}.mp4"}
