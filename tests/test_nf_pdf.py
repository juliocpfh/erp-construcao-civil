"""NF em PDF: DANFE gerado por sistema (texto) e PDF escaneado (OCR das páginas)."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from erp import auth, db
from erp.services import ocr

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data"

DANFE_LINES = [
    "DANFE - DOCUMENTO AUXILIAR DA NOTA FISCAL ELETRONICA",
    "Deposito Curitibano de Materiais Ltda",
    "CNPJ: 12.345.678/0001-95",
    "NF-e N. 4521   DATA DA EMISSAO: 28/09/2026",
    "DESCRICAO QTD UN VL UNIT",
    "001234 CIMENTO CP-II 50KG 25232910 000 5102 SC 120 38,50 4.620,00",
    "VALOR TOTAL DA NOTA: R$ 4.620,00",
]


def _text_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in DANFE_LINES:
        c.drawString(40, y, line)
        y -= 18
    c.save()
    return buf.getvalue()


def test_text_pdf_is_read_without_ocr():
    data = _text_pdf()
    assert ocr.is_pdf(data)
    res = ocr.read_invoice(data)
    assert res["engine"] == "texto do PDF"
    assert res["fields"]["valor"] == 4620.0 and res["fields"]["cnpj"] == "12.345.678/0001-95"
    assert res["fields"]["numero"] == "4521"
    assert [(i["description"], i["quantity"], i["unit"], i["unit_price"]) for i in res["items"]] == [
        ("CIMENTO CP-II 50KG", 120.0, "sc", 38.5)]


def test_pdf_preview_renders_first_page():
    pages = ocr.pdf_page_images(_text_pdf(), max_pages=1, scale=1)
    assert len(pages) == 1 and pages[0][:8] == b"\x89PNG\r\n\x1a\n"


def test_scanned_pdf_goes_through_ocr():
    buf = io.BytesIO()
    Image.open(SAMPLE / "nf_exemplo.png").convert("RGB").save(buf, format="PDF", resolution=150)
    res = ocr.read_invoice(buf.getvalue())
    assert res["engine"].startswith("PDF escaneado")
    if ocr.ocr_available():
        assert any("bloco" in i["description"].lower() and i["quantity"] == 6000 for i in res["items"])


def test_invalid_pdf_raises_friendly_error():
    try:
        ocr.read_invoice(b"%PDF-1.4 quebrado")
    except ValueError as exc:
        assert "PDF" in str(exc)
    else:
        raise AssertionError("esperava ValueError")


def test_users_with_fiscal_keep_nf_access(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    db.init_db(path)
    conn = db.connect(path)
    conn.execute("DELETE FROM settings WHERE key = 'perm_nfs_migrated'")
    conn.execute("INSERT INTO users(username, password_hash, role, full_name, created_at) "
                 "VALUES ('eng', 'x', 'Visualizador', 'Eng', '2026-01-01')")
    uid = conn.execute("SELECT id FROM users WHERE username = 'eng'").fetchone()[0]
    conn.execute("INSERT INTO user_permissions(user_id, module) VALUES (?, 'fiscal')", (uid,))
    conn.commit()
    conn.close()
    db.init_db(path)
    db.init_db(path)  # idempotente
    conn = db.connect(path)
    mods = {r[0] for r in conn.execute("SELECT module FROM user_permissions WHERE user_id = ?", (uid,))}
    conn.close()
    assert mods == {"fiscal", "nfs"}
    assert "nfs" in auth.MODULES


# DANFE real em texto (estrutura de um PDF emitido por ERP de loja; dados fictícios)
DANFE_TEXT = """RECEBI(EMOS) DE LOJA EXEMPLO ESPORTES LTDA, OS PRODUTOS CONSTANTE DA NOTA FISCAL ELETRÔNICA INDICADA AO LADO,
NF-e
No.
SÉRIE
000.310.631
LOJA EXEMPLO ESPORTES LTDA
PROTOCOLO DE AUTORIZAÇÃO DE USO
141260215229757 - 03-06-2026 16:24:25
INSCRIÇÃO ESTADUAL DO SUBST. TRIB. C.N.P.J.
02.314.041/0016-64
 DESTINATÁRIO/ REMETENTE
NOME/RAZÃO SOCIAL
CONSTRUTORA CLIENTE LTDA
C.N.P.J./C.P.F.
62.955.505/0066-02
DATA DA EMISSÃO
03-06-2026 16:24:07
VALOR TOTAL DOS PRODUTOS
279,98
VALOR TOTAL DA NOTA
279,98
DADOS DOS PRODUTOS/SERVIÇOS
CÓDIGO DESCRIÇÃO NCM/SH CST CFOP  UN. QUANT. V.UNIT. DESCONTO V.TOTAL BC.ICMS V.ICMS V.IPI %ICMS %IPI
5766741 BOLA DE FUTEBOL DE CAMPO PENALTY 95066200000 5929 UN 1,0000 99,9900 0,00 99,99 99,99 19,50 0,00 19,50 0,00
BRAVO XXV
6048443 BOLA VOLEI VP 5100 XXVI SANS 95066200000 5929 UN 2,0000 90,0000 0,01 179,99 179,99 35,10 0,00 19,50 0,00
TAILLE
DADOS ADICIONAIS
INFORMAÇÕES COMPLEMENTARES RESERVADO AO FISCO
"""


def test_danfe_text_with_tax_columns_and_wrapped_descriptions():
    res = ocr.read_invoice(None, DANFE_TEXT)
    f = res["fields"]
    assert f["fornecedor"] == "LOJA EXEMPLO ESPORTES LTDA"  # emitente, não o destinatário
    assert f["cnpj"] == "02.314.041/0016-64" and f["numero"] == "310631" and f["valor"] == 279.98
    assert [(i["description"], i["quantity"], i["unit"], i["unit_price"], i["total"], i["supplier_code"])
            for i in res["items"]] == [
        ("BOLA DE FUTEBOL DE CAMPO PENALTY BRAVO XXV", 1.0, "un", 99.99, 99.99, "5766741"),
        ("BOLA VOLEI VP 5100 XXVI SANS TAILLE", 2.0, "un", 90.0, 179.99, "6048443")]  # com desconto


def test_danfe_ocr_noise_is_ignored():
    text = ("DADOS DOS PRODUTOS/SERVIÇOS\n[ocónrco | DESEN [SME Jeso o [IT OESCOMO | VODI [ EEIOS\n"
            "5766741 BOLA DE FUTEBOL 95066200000 [5929] UN 1,0000 | 99,9900 0,00 99,99 99,99 | 19,50 0,00 [19,50 | 0,00\n"
            "DA | =): 4:40 0 64 A PD PAD, PI A PR PA PP A DP\nDADOS ADICIONAIS\n")
    from erp.services import nf_import

    items = nf_import.parse_items_text(text)
    assert [(i.description, i.quantity, i.unit_price, i.total) for i in items] == [("BOLA DE FUTEBOL", 1.0, 99.99, 99.99)]


def test_danfe_values_below_labels_in_columns():
    text = ("BASE DE CÁLCULO DO ICMS VALOR DO ICMS B.C. DO ICMS ST |VALOR TOTAL DOS PRODUTOS\n279,98 54,60 0,00 279,98\n"
            "[VALOR DO FRETE [VALOR DO SEGURO [DESCONTO OUTRAS DESPESAS |VALOR DO IPI (VALOR TOTAL DA NOTA\n"
            "0,00 0,00 0,00 0,00 0,00 279,98\n")
    assert ocr.parse_invoice_text(text)["valor"] == 279.98


def test_column_layout_pdf_reads_all_items():
    from tests.danfe_fixture import EXPECTED, danfe_pdf

    res = ocr.read_invoice(danfe_pdf())
    assert res["fields"]["fornecedor"] == "DEPOSITO CURITIBANO DE MATERIAIS LTDA"
    assert res["fields"]["numero"] == "4521" and res["fields"]["valor"] == 35559.5
    assert [(i["description"], i["quantity"], i["unit"], i["unit_price"], i["total"], i["supplier_code"])
            for i in res["items"]] == EXPECTED
