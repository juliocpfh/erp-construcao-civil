"""Gestão de NFs: lançamento (PDF, foto, XML ou texto), materiais automáticos, aprovação (CR) e histórico."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from erp import auth, db
from erp.config import INVOICE_STATUS
from erp.services import evm, finance, inventory, nf_import, ocr
from erp.storage import load_media, store_media
from erp.ui.common import (
    blink_alert,
    can_edit,
    current_user,
    header,
    money,
    read_only_notice,
    username,
)

KINDS = ["Material", "Serviço", "Material + Mão de obra"]
AUTO = "➕ Cadastrar automaticamente"


def _items_frame(res: dict | None, mat_names: list[str], materials: list[dict]) -> pd.DataFrame:
    """Itens lidos da NF já casados com os materiais existentes (ou marcados para cadastro automático)."""
    cols = ["Descrição", "Quantidade", "Unidade", "Preço unitário", "Material", "Código fornecedor"]
    found = (res or {}).get("items") or []
    if not found:
        return pd.DataFrame({c: pd.Series([], dtype="float" if c in ("Quantidade", "Preço unitário") else "object")
                             for c in cols})
    by_id = {m["id"]: label for m, label in zip(materials, mat_names)}
    resolved = nf_import.resolve_items(found, st.session_state.get("nf_cnpj"))
    return pd.DataFrame([{"Descrição": it["description"], "Quantidade": it["quantity"], "Unidade": it["unit"],
                          "Preço unitário": it["unit_price"], "Material": by_id.get(it["material_id"], AUTO),
                          "Código fornecedor": it.get("supplier_code", "")} for it in resolved], columns=cols)


def render() -> None:
    header("Gestão de NFs", "Lance a NF em PDF, foto ou XML. NF aprovada dá entrada no estoque e soma ao Custo Real (CR).")
    n = db.query_one("SELECT COUNT(*) AS n FROM invoices WHERE status = 'Pendente'")["n"]
    tabs = st.tabs(["➕ Incluir NF", f"✅ Aprovação ({n})", "📋 Todas as NFs"])
    with tabs[0]:
        _launch() if can_edit() else read_only_notice()
    with tabs[1]:
        _approval()
    with tabs[2]:
        _history()


def _kind_of(f) -> str:
    name = (getattr(f, "name", "") or "").lower()
    data = f.getvalue()[:5]
    if name.endswith(".xml"):
        return "xml"
    if name.endswith(".pdf") or data == b"%PDF-":
        return "pdf"
    return "img"


def show_nf_document(data: bytes | None, key: str | None, container, label: str = "Nota fiscal") -> None:
    """Mostra a NF salva: imagem direto; PDF como imagem da 1ª página + botão para baixar o PDF."""
    if not data:
        return
    if ocr.is_pdf(data):
        try:
            container.image(ocr.pdf_page_images(data, max_pages=1, scale=1.5)[0], caption=label, width="stretch")
        except Exception:  # noqa: BLE001
            container.caption(f"{label} (PDF)")
        container.download_button("📄 Abrir PDF da NF", data, file_name=(key or "nf.pdf").rsplit("/", 1)[-1],
                                  mime="application/pdf", key=f"pdf_{key}")
    else:
        container.image(data, caption=label, width="stretch")


def _launch() -> None:
    if saved := st.session_state.pop("nf_saved_msg", None):
        st.success(saved)
    if st.session_state.pop("nf_reset", False):  # antes de desenhar os campos (depois o Streamlit não deixa)
        st.session_state.update(nf_supplier="", nf_cnpj="", nf_number="", nf_value=0.0, nf_issue=date.today(),
                                nf_iss=0.0, nf_inss=0.0, nf_text="")
    st.caption(f"Motor de OCR: {'Tesseract disponível ✅' if ocr.ocr_available() else 'indisponível — cole o texto da NF para preenchimento automático'}")
    c1, c2 = st.columns(2)
    with c1:
        use_cam = st.toggle("Tirar foto com a câmera do celular", value=False, key="nf_cam")
        if use_cam:
            cam = st.camera_input("Foto da Nota Fiscal")
            files = [cam] if cam else []
        else:
            files = st.file_uploader("Arquivo da NF: PDF (DANFE), foto ou XML da NF-e. Pode enviar o PDF e o XML juntos.",
                                     type=["pdf", "xml", "jpg", "jpeg", "png", "webp"], accept_multiple_files=True,
                                     key=f"nf_up_{st.session_state.get('nf_form_rev', 0)}") or []
    with c2:
        prod_file = st.file_uploader("Foto do Produto/Serviço entregue (opcional)", type=["jpg", "jpeg", "png", "webp"],
                                     key=f"prod_up_{st.session_state.get('nf_form_rev', 0)}")
        if prod_file:
            st.image(prod_file, width=260)
    xml_file = next((f for f in files if _kind_of(f) == "xml"), None)
    nf_file = next((f for f in files if _kind_of(f) == "pdf"), None) or next(
        (f for f in files if _kind_of(f) == "img"), None)
    pasted = st.text_area("Texto da NF (opcional: use quando não houver arquivo ou para conferência)", height=90,
                          key="nf_text")

    if st.button("🔍 Ler NF e preencher automaticamente", type="primary"):
        if nf_file is None and not pasted and xml_file is None:
            st.warning("Envie o PDF, a foto ou o XML da NF, ou cole o texto.")
        else:
            with st.spinner("Lendo nota fiscal..."):
                try:
                    if xml_file is not None:
                        parsed = nf_import.parse_nfe_xml(xml_file.getvalue())
                        result = {"text": "", "engine": parsed["engine"], "fields": parsed["fields"],
                                  "items": [i.as_dict() for i in parsed["items"]], "confidence": 1.0}
                    else:
                        result = ocr.read_invoice(nf_file.getvalue() if nf_file and not pasted else None, pasted or None)
                except ValueError as exc:
                    st.error(str(exc))
                    return
            st.session_state["ocr_result"] = result
            st.session_state["nf_items_rev"] = st.session_state.get("nf_items_rev", 0) + 1
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
        st.info(f"Leitura ({res['engine']}): {int(res['confidence'] * 3)}/3 campos-chave (Valor, Fornecedor, Emissão) "
                f"identificados · {len(res.get('items', []))} item(ns) de material encontrado(s).")
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
        st.markdown("**Itens de material** — materiais que ainda não existem são **cadastrados automaticamente** "
                    "ao registrar a NF; a entrada no estoque acontece na aprovação/conferência.")
        items = st.data_editor(_items_frame(res, mat_names, materials), num_rows="dynamic", hide_index=True,
                               key=f"nf_items_{st.session_state.get('nf_items_rev', 0)}", width="stretch",
                               column_config={
                                   "Material": st.column_config.SelectboxColumn(options=[AUTO] + mat_names, required=True,
                                                                                help="Deixe em 'cadastrar' para criar o material"),
                                   "Quantidade": st.column_config.NumberColumn(min_value=0.0, format="%.3f"),
                                   "Preço unitário": st.column_config.NumberColumn(min_value=0.0, format="R$ %.4f"),
                                   "Código fornecedor": None})
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
        default = "nf.pdf" if _kind_of(nf_file) == "pdf" else "nf.jpg"
        r = store_media(nf_file.getvalue(), getattr(nf_file, "name", default) or default, "notas-fiscais")
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
    rows = []
    for r in items.to_dict("records"):
        mat = r.get("Material") or AUTO
        m = materials[mat_names.index(mat)] if mat in mat_names else None
        desc = str(r.get("Descrição") or "").strip() or (m["name"] if m else "")
        if not desc or not r.get("Quantidade"):
            continue
        rows.append({"description": desc, "quantity": float(r["Quantidade"]), "unit": r.get("Unidade") or (m["unit"] if m else "un"),
                     "unit_price": float(r.get("Preço unitário") or (m["unit_cost"] if m else 0) or 0),
                     "supplier_code": str(r.get("Código fornecedor") or ""), "material_id": m["id"] if m else None})
    reg = nf_import.register_items(inv_id, rows, cnpj)
    if approve_now:
        inventory.approve_invoice(inv_id, username())
    msg = f"NF registrada ({'aprovada e com entrada no estoque' if approve_now else 'pendente de aprovação'})."
    if reg["created"]:
        msg += f" {reg['created']} material(is) novo(s) cadastrado(s) automaticamente."
    if reg["linked"]:
        msg += f" {reg['linked']} item(ns) vinculado(s) a materiais existentes."
    st.session_state["nf_saved_msg"] = msg + (" " + " | ".join(storage_msgs) if storage_msgs else "")
    st.session_state["nf_items_rev"] = st.session_state.get("nf_items_rev", 0) + 1
    st.session_state.pop("ocr_result", None)
    st.session_state["nf_form_rev"] = st.session_state.get("nf_form_rev", 0) + 1  # esvazia os campos de arquivo
    st.session_state["nf_reset"] = True  # formulário limpo para a próxima NF (evita lançar a mesma duas vezes)
    st.rerun()  # atualiza a contagem de pendentes na aba Aprovação


def _approval() -> None:
    pending = db.query("SELECT i.*, t.code AS task_code FROM invoices i LEFT JOIN tasks t ON t.id = i.task_id "
                       "WHERE status = 'Pendente' ORDER BY issue_date")
    st.markdown(f"**{len(pending)} NF(s) pendente(s)**")
    before = evm.evm_snapshot()
    for inv in pending:
        with st.container(border=True):
            c1, c2 = st.columns([1, 2])
            show_nf_document(load_media(inv["nf_media_key"]), inv["nf_media_key"], c1)
            prod = load_media(inv["product_media_key"])
            if prod:
                c1.image(prod, caption="Produto/serviço", width="stretch")
            c2.markdown(f"**NF {inv['number']} · {inv['supplier_name']}**  \n{inv['supplier_cnpj'] or ''}  \n"
                        f"Emissão {date.fromisoformat(inv['issue_date']):%d/%m/%Y} · {inv['kind']} · Tarefa {inv['task_code'] or '-'}")
            c2.metric("Valor", money(inv["total_value"]))
            c2.caption(f"ISS {money(inv['iss_value'])} · INSS {money(inv['inss_value'])} · {inv['tax_benefit'] or ''}"
                       .replace("$", "\\$"))
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
    if not pending:
        st.info("Nenhuma NF aguardando aprovação.")


def _history() -> None:
    c1, c2 = st.columns([1, 2])
    status = c1.multiselect("Situação", INVOICE_STATUS, default=INVOICE_STATUS, key="nf_hist_status")
    search = c2.text_input("Buscar fornecedor ou número", key="nf_hist_q").strip()
    rows = db.query("SELECT i.id, i.issue_date, i.number, i.supplier_name, i.kind, t.code AS task_code, i.total_value, "
                    "i.iss_value, i.inss_value, i.status, i.nf_media_key FROM invoices i "
                    "LEFT JOIN tasks t ON t.id = i.task_id ORDER BY i.issue_date DESC, i.id DESC")
    q = search.lower()
    rows = [r for r in rows if r["status"] in status and
            (not q or q in (r["supplier_name"] or "").lower() or q in (r["number"] or "").lower())]
    hist = pd.DataFrame([{"Emissão": r["issue_date"], "NF": r["number"], "Fornecedor": r["supplier_name"],
                          "Tipo": r["kind"], "Tarefa": r["task_code"], "Valor": r["total_value"], "ISS": r["iss_value"],
                          "INSS": r["inss_value"], "Status": r["status"]} for r in rows],
                        columns=["Emissão", "NF", "Fornecedor", "Tipo", "Tarefa", "Valor", "ISS", "INSS", "Status"])
    st.caption(f"{len(rows)} NF(s) · total {money(sum(r['total_value'] or 0 for r in rows))}")
    st.dataframe(hist, hide_index=True, width="stretch", height=380,
                 column_config={k: st.column_config.NumberColumn(format="R$ %.2f") for k in ("Valor", "ISS", "INSS")})
    with_doc = {f"NF {r['number']} · {r['supplier_name']}": r for r in rows if r["nf_media_key"]}
    if with_doc:
        pick = st.selectbox("Ver o documento da NF", ["-"] + list(with_doc), key="nf_hist_doc")
        if pick != "-":
            r = with_doc[pick]
            show_nf_document(load_media(r["nf_media_key"]), r["nf_media_key"], st, pick)


