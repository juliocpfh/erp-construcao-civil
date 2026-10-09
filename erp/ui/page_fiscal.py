"""Comprovação fiscal: NF + foto do produto, OCR, aprovação (CR), BDI, cotações e EVM."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from erp import auth, db
from erp.services import evm, finance, inventory, ocr
from erp.storage import load_media, store_media
from erp.ui import charts
from erp.ui.common import blink_alert, can_edit, current_user, header, money, money_short, read_only_notice, username

KINDS = ["Material", "Serviço", "Material + Mão de obra"]


def render() -> None:
    header("Comprovação Fiscal, Tributos e OCR", "NF aprovada soma ao Custo Real (CR) e atualiza IDC, IDP e Curva S.")
    tabs = st.tabs(["📸 Lançar NF (OCR)", "✅ Aprovação", "🧮 BDI & Tributos", "📨 Cotações", "📈 Custos (PMI)"])
    with tabs[0]:
        _launch() if can_edit() else read_only_notice()
    with tabs[1]:
        _approval()
    with tabs[2]:
        _bdi()
    with tabs[3]:
        _quotes()
    with tabs[4]:
        _costs()


def _launch() -> None:
    st.caption(f"Motor de OCR: {'Tesseract disponível ✅' if ocr.ocr_available() else 'indisponível — cole o texto da NF para preenchimento automático'}")
    c1, c2 = st.columns(2)
    with c1:
        use_cam = st.toggle("Usar câmera do celular", value=False, key="nf_cam")
        nf_file = st.camera_input("Foto da Nota Fiscal") if use_cam else st.file_uploader(
            "Foto/imagem da Nota Fiscal", type=["jpg", "jpeg", "png", "webp"], key="nf_up")
    with c2:
        prod_file = st.file_uploader("Foto do Produto/Serviço entregue", type=["jpg", "jpeg", "png", "webp"], key="prod_up")
        if prod_file:
            st.image(prod_file, width=260)
    pasted = st.text_area("Texto da NF (opcional — usado quando não há OCR ou para conferência)", height=90, key="nf_text")

    if st.button("🔍 Ler NF e preencher automaticamente", type="primary"):
        if nf_file is None and not pasted:
            st.warning("Envie a foto da NF ou cole o texto.")
        else:
            with st.spinner("Lendo nota fiscal..."):
                result = ocr.read_invoice(nf_file.getvalue() if nf_file and not pasted else None, pasted or None)
            st.session_state["ocr_result"] = result
            f = result["fields"]
            st.session_state["nf_supplier"] = f["fornecedor"] or ""
            st.session_state["nf_cnpj"] = f["cnpj"] or ""
            st.session_state["nf_number"] = f["numero"] or ""
            st.session_state["nf_value"] = float(f["valor"] or 0.0)
            st.session_state["nf_issue"] = f["emissao"] or date.today()
            st.session_state["nf_iss"] = float(f["iss"] or 0.0)
            st.session_state["nf_inss"] = float(f["inss"] or 0.0)
    res = st.session_state.get("ocr_result")
    if res:
        st.info(f"OCR ({res['engine']}): {int(res['confidence'] * 3)}/3 campos-chave (Valor, Fornecedor, Emissão) identificados.")
        with st.expander("Texto reconhecido"):
            st.code(res["text"] or "(vazio)")

    tasks = {f"{t['code']} · {t['name']}": t["id"] for t in db.query("SELECT id, code, name FROM tasks ORDER BY code")}
    materials = db.query("SELECT id, code, name, unit, unit_cost FROM materials ORDER BY name")
    mat_names = [f"{m['code']} · {m['name']} ({m['unit']})" for m in materials]
    with st.form("nf_form"):
        c1, c2, c3 = st.columns(3)
        supplier = c1.text_input("Fornecedor (Razão social)", key="nf_supplier")
        cnpj = c2.text_input("CNPJ", key="nf_cnpj")
        number = c3.text_input("Número da NF", key="nf_number")
        c1, c2, c3 = st.columns(3)
        value = c1.number_input("Valor total (R$)", 0.0, 1e9, step=100.0, key="nf_value")
        issue = c2.date_input("Emissão", key="nf_issue", format="DD/MM/YYYY")
        kind = c3.selectbox("Tipo", KINDS)
        c1, c2, c3 = st.columns(3)
        iss = c1.number_input("ISS destacado (R$)", 0.0, 1e9, step=10.0, key="nf_iss")
        inss = c2.number_input("Retenção INSS (R$)", 0.0, 1e9, step=10.0, key="nf_inss")
        benefit = c3.text_input("Benefício fiscal", placeholder="Ex.: desoneração CPRB, redução de ISS")
        task = st.selectbox("Tarefa do cronograma (centro de custo)", ["-"] + list(tasks))
        st.markdown("**Itens de material** (alimentam o estoque quando a NF é aprovada)")
        items = st.data_editor(pd.DataFrame({"Material": pd.Series([], dtype="object"),
                                             "Quantidade": pd.Series([], dtype="float"),
                                             "Preço unitário": pd.Series([], dtype="float")}),
                               num_rows="dynamic", hide_index=True, key="nf_items", width="stretch",
                               column_config={"Material": st.column_config.SelectboxColumn(options=mat_names)})
        approve_now = st.checkbox("Aprovar imediatamente (Administrador)", disabled=not auth.is_admin(current_user()))
        submit = st.form_submit_button("💾 Registrar NF", type="primary")
    if not submit:
        return
    if not supplier or value <= 0:
        st.error("Fornecedor e valor são obrigatórios.")
        return
    for a in finance.invoice_tax_alerts(kind, value, iss, inss):
        blink_alert("⚠️ Alerta fiscal: " + a, level="warning", blink=False)
    nf_key = prod_key = None
    storage_msgs = []
    if nf_file is not None:
        r = store_media(nf_file.getvalue(), getattr(nf_file, "name", "nf.jpg") or "nf.jpg", "notas-fiscais")
        nf_key = r.key
        storage_msgs.append(f"NF → S3: {r.s3} · FTP: {r.ftp}")
    if prod_file is not None:
        r = store_media(prod_file.getvalue(), prod_file.name, "fotos-produtos")
        prod_key = r.key
        storage_msgs.append(f"Produto → S3: {r.s3} · FTP: {r.ftp}")
    res = st.session_state.get("ocr_result") or {}
    inv_id = db.execute(
        "INSERT INTO invoices(number, supplier_name, supplier_cnpj, issue_date, total_value, kind, iss_value, inss_value, "
        "tax_benefit, task_id, status, nf_media_key, product_media_key, ocr_text, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,'Pendente',?,?,?,?)",
        (number, supplier, cnpj, issue.isoformat(), value, kind, iss, inss, benefit, tasks.get(task), nf_key, prod_key,
         res.get("text", ""), db.now_iso()))
    for r in items.dropna().itertuples():
        if r.Material in mat_names and r.Quantidade:
            m = materials[mat_names.index(r.Material)]
            db.execute("INSERT INTO invoice_items(invoice_id, material_id, quantity, unit_price) VALUES (?,?,?,?)",
                       (inv_id, m["id"], float(r.Quantidade), float(r[3] or m["unit_cost"])))
    if approve_now:
        inventory.approve_invoice(inv_id, username())
    st.success(f"NF registrada ({'aprovada' if approve_now else 'pendente de aprovação'}). " + " | ".join(storage_msgs))
    st.session_state.pop("ocr_result", None)


def _approval() -> None:
    pending = db.query("SELECT i.*, t.code AS task_code FROM invoices i LEFT JOIN tasks t ON t.id = i.task_id "
                       "WHERE status = 'Pendente' ORDER BY issue_date")
    st.markdown(f"**{len(pending)} NF(s) pendente(s)**")
    before = evm.evm_snapshot()
    for inv in pending:
        with st.container(border=True):
            c1, c2 = st.columns([1, 2])
            img = load_media(inv["nf_media_key"])
            if img:
                c1.image(img, caption="Nota fiscal", width="stretch")
            prod = load_media(inv["product_media_key"])
            if prod:
                c1.image(prod, caption="Produto/serviço", width="stretch")
            c2.markdown(f"**NF {inv['number']} · {inv['supplier_name']}**  \n{inv['supplier_cnpj'] or ''}  \n"
                        f"Emissão {date.fromisoformat(inv['issue_date']):%d/%m/%Y} · {inv['kind']} · Tarefa {inv['task_code'] or '-'}")
            c2.metric("Valor", money(inv["total_value"]))
            c2.caption(f"ISS {money(inv['iss_value'])} · INSS {money(inv['inss_value'])} · {inv['tax_benefit'] or ''}")
            for a in finance.invoice_tax_alerts(inv["kind"], inv["total_value"], inv["iss_value"], inv["inss_value"]):
                c2.warning(a)
            items = db.query_df("SELECT m.name AS Material, ii.quantity AS Qtd, m.unit AS Un, ii.unit_price AS 'Preço un.' "
                                "FROM invoice_items ii JOIN materials m ON m.id = ii.material_id WHERE invoice_id = ?",
                                (inv["id"],))
            if not items.empty:
                c2.dataframe(items, hide_index=True, width="stretch")
            if can_edit():
                b1, b2 = c2.columns(2)
                if b1.button("✅ Aprovar", key=f"ap_{inv['id']}", type="primary"):
                    inventory.approve_invoice(inv["id"], username())
                    after = evm.evm_snapshot()
                    st.toast(f"CR {money(before['CR'])} → {money(after['CR'])} · IDC {before['IDC']:.3f} → {after['IDC']:.3f}")
                    st.rerun()
                if b2.button("❌ Rejeitar", key=f"rj_{inv['id']}"):
                    inventory.reject_invoice(inv["id"], username())
                    st.rerun()
    st.divider()
    st.markdown("**Histórico de NFs**")
    hist = db.query_df("SELECT i.issue_date AS Emissão, i.number AS NF, i.supplier_name AS Fornecedor, i.kind AS Tipo, "
                       "t.code AS Tarefa, i.total_value AS Valor, i.iss_value AS ISS, i.inss_value AS INSS, i.status AS Status "
                       "FROM invoices i LEFT JOIN tasks t ON t.id = i.task_id ORDER BY i.issue_date DESC")
    st.dataframe(hist, hide_index=True, width="stretch", height=380,
                 column_config={k: st.column_config.NumberColumn(format="R$ %.2f") for k in ("Valor", "ISS", "INSS")})


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
