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
