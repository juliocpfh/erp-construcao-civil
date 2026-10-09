"""Central de Projetos, Quantitativos e Laudos (GED) com versionamento."""
from __future__ import annotations

import streamlit as st

from erp import db
from erp.config import GED_FOLDERS
from erp.storage import load_media, store_media
from erp.ui.common import can_edit, header, username

ALLOWED = ["pdf", "dwg", "dxf", "ifc", "rvt", "skp", "xlsx", "xls", "csv", "docx", "zip", "jpg", "png"]
ICONS = {"pdf": "📕", "dwg": "📐", "dxf": "📐", "ifc": "🧊", "rvt": "🧊", "csv": "📊", "xlsx": "📊", "xls": "📊", "zip": "🗜️"}


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def render() -> None:
    header("Central de Projetos, Quantitativos e Laudos (GED)",
           "Arquivos pesados (PDF, DWG, IFC...) com armazenamento duplo S3 + FTP e controle de versão.")
    stats = db.query("SELECT folder, COUNT(*) n, SUM(size_bytes) s FROM ged_files GROUP BY folder")
    cols = st.columns(len(GED_FOLDERS))
    by = {r["folder"]: r for r in stats}
    for c, f in zip(cols, GED_FOLDERS):
        c.metric(f"📁 {f}", by.get(f, {}).get("n", 0), _size(by.get(f, {}).get("s", 0) or 0), delta_color="off")

    if can_edit():
        with st.expander("⬆️ Enviar arquivos", expanded=False):
            with st.form("ged_up", clear_on_submit=True):
                c = st.columns(2)
                folder = c[0].selectbox("Pasta", GED_FOLDERS)
                disc = c[1].text_input("Disciplina", placeholder="Arquitetura, Estrutura, BIM, Ambiental...")
                files = st.file_uploader("Arquivos", type=ALLOWED, accept_multiple_files=True)
                notes = st.text_input("Observações / revisão")
                if st.form_submit_button("Enviar", type="primary") and files:
                    for f in files:
                        data = f.getvalue()
                        prev = db.query_one("SELECT MAX(version) v FROM ged_files WHERE folder = ? AND filename = ?",
                                            (folder, f.name))
                        version = (prev["v"] or 0) + 1 if prev else 1
                        r = store_media(data, f.name, f"ged-{folder}")
                        db.execute("INSERT INTO ged_files(folder, discipline, title, filename, extension, size_bytes, version, "
                                   "media_key, uploaded_by, uploaded_at, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                   (folder, disc, f.name.rsplit(".", 1)[0], f.name, f.name.rsplit(".", 1)[-1].lower(),
                                    len(data), version, r.key, username(), db.now_iso(), notes))
                        st.success(f"{f.name} v{version} — S3: {r.s3} · FTP: {r.ftp} · local: {r.local}")

    tabs = st.tabs([f"📁 {f}" for f in GED_FOLDERS])
    search = st.text_input("🔎 Buscar arquivo", key="ged_search")
    for tab, folder in zip(tabs, GED_FOLDERS):
        with tab:
            files = db.query("SELECT * FROM ged_files WHERE folder = ? ORDER BY discipline, filename, version DESC", (folder,))
            if search:
                files = [f for f in files if search.lower() in (f["title"] + f["filename"] + (f["discipline"] or "")).lower()]
            if not files:
                st.caption("Pasta vazia.")
            for f in files:
                with st.container(border=True):
                    c1, c2 = st.columns([4, 1])
                    c1.markdown(f"{ICONS.get(f['extension'], '📄')} **{f['title']}** · v{f['version']}  \n"
                                f"{f['filename']} · {f['discipline'] or '-'} · {_size(f['size_bytes'] or 0)} · "
                                f"enviado por {f['uploaded_by']} em {f['uploaded_at'][:10]}")
                    if c2.button("Preparar download", key=f"gp_{f['id']}"):
                        st.session_state[f"ged_{f['id']}"] = load_media(f["media_key"])
                    data = st.session_state.get(f"ged_{f['id']}")
                    if data:
                        c2.download_button("⬇️ Baixar", data, file_name=f["filename"], key=f"gd_{f['id']}")
