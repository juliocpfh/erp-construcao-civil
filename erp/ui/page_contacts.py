"""Agenda: importação de vCard (.vcf) e timeline do histórico de cada envolvido."""
from __future__ import annotations

import html

import streamlit as st

from erp import db
from erp.config import BASE_DIR
from erp.services import contacts
from erp.ui import charts
from erp.ui.common import can_edit, header, money

SAMPLE_VCF = BASE_DIR / "sample_data" / "contatos_obra.vcf"


def render() -> None:
    header("Agenda e Importação de Contatos (vCard)",
           "Importe .vcf do celular; a timeline mostra tarefas gerenciadas, RDOs assinados e NFs emitidas.")
    if can_edit():
        with st.expander("📥 Importar contatos (.vcf)", expanded=False):
            up = st.file_uploader("Arquivo vCard", type=["vcf", "vcard"])
            if SAMPLE_VCF.exists():
                st.download_button("Baixar .vcf de exemplo", SAMPLE_VCF.read_bytes(), file_name=SAMPLE_VCF.name)
            if up:
                cards = contacts.parse_vcf(up.getvalue())
                st.write(f"{len(cards)} contato(s) encontrado(s):")
                st.dataframe([{"Nome": c["name"], "Telefone": contacts.format_phone(c["phone"]), "E-mail": c["email"],
                               "Empresa": c["organization"], "Cargo": c["title"]} for c in cards],
                             hide_index=True, width="stretch")
                if st.button("Importar para a agenda", type="primary"):
                    r = contacts.import_contacts(cards)
                    st.success(f"{r['created']} criado(s), {r['updated']} atualizado(s), "
                               f"{r['linked_invoices']} NF(s) vinculada(s) ao emitente.")

    df = db.query_df("SELECT id, name, phone, email, organization, title, category, source FROM contacts ORDER BY name")
    c1, c2 = st.columns([2, 1])
    q = c1.text_input("🔎 Buscar contato")
    cats = c2.multiselect("Categoria", sorted(df["category"].dropna().unique()))
    view = df
    if q:
        mask = view.apply(lambda r: q.lower() in " ".join(str(v) for v in r.values).lower(), axis=1)
        view = view[mask]
    if cats:
        view = view[view["category"].isin(cats)]
    st.dataframe(view.drop(columns=["id"]).rename(columns={
        "name": "Nome", "phone": "Telefone", "email": "E-mail", "organization": "Empresa", "title": "Cargo",
        "category": "Categoria", "source": "Origem"}), hide_index=True, width="stretch", height=300)

    st.subheader("🕒 Timeline do envolvido")
    if view.empty:
        return
    opts = {f"{r.name} — {r.organization or ''}": int(r.id) for r in view.itertuples()}
    sel = st.selectbox("Contato", list(opts))
    events = contacts.contact_timeline(opts[sel])
    counts = {t: sum(1 for e in events if e["type"] == t) for t in ("Tarefa gerenciada", "RDO assinado", "NF emitida")}
    c = st.columns(4)
    c[0].metric("Tarefas gerenciadas", counts["Tarefa gerenciada"])
    c[1].metric("RDOs assinados", counts["RDO assinado"])
    c[2].metric("NFs emitidas", counts["NF emitida"])
    c[3].metric("Valor faturado", money(sum(e.get("value", 0) for e in events)))
    fig = charts.contact_timeline(events)
    if fig:
        st.plotly_chart(fig, width="stretch")
    if not events:
        st.info("Sem histórico vinculado a este contato.")
        return
    shown = events[-60:]
    items = "".join(
        f'<div class="ev"><b>{html.escape(e["date"] or "—")}</b> · {html.escape(e["type"])}<br>'
        f'{html.escape(e["description"])}</div>' for e in reversed(shown))
    st.markdown(f'<div class="erp-timeline">{items}</div>', unsafe_allow_html=True)
    if len(events) > len(shown):
        st.caption(f"Exibindo os {len(shown)} eventos mais recentes de {len(events)}.")
