from datetime import date

import pytest

from erp.services import ocr
from erp.services.simulation_media import render_invoice_image

SAMPLE = """DANFE - DOCUMENTO AUXILIAR DA NF-e
RAZÃO SOCIAL: Concreteira Pinheiral Ltda
CNPJ: 12.345.678/0001-95
NF-e Nº 004521 SÉRIE 1
DATA DE EMISSÃO: 28/09/2026
VALOR DO ISS: R$ 312,50
RETENÇÃO INSS: R$ 1.375,00
VALOR TOTAL DA NOTA: R$ 57.200,00
"""


def test_parse_invoice_text():
    f = ocr.parse_invoice_text(SAMPLE)
    assert f["fornecedor"] == "Concreteira Pinheiral Ltda"
    assert f["cnpj"] == "12.345.678/0001-95"
    assert f["numero"] == "004521"
    assert f["valor"] == pytest.approx(57200.00)
    assert f["emissao"] == date(2026, 9, 28)
    assert f["iss"] == pytest.approx(312.5)
    assert f["inss"] == pytest.approx(1375.0)


def test_parse_money_formats():
    assert ocr.parse_money("1.234,56") == pytest.approx(1234.56)
    assert ocr.parse_money("1234.56") == pytest.approx(1234.56)


def test_supplier_fallback_by_company_suffix():
    f = ocr.parse_invoice_text("ACO IGUACU DISTRIBUIDORA LTDA\nTOTAL R$ 10,00\n01/02/2026")
    assert "LTDA" in f["fornecedor"]
    assert f["valor"] == pytest.approx(10.0)
    assert f["emissao"] == date(2026, 2, 1)


def test_read_invoice_from_pasted_text_without_engine():
    r = ocr.read_invoice(text=SAMPLE)
    assert r["engine"] == "texto informado"
    assert r["confidence"] == 1


def test_preprocess_rejects_invalid_image():
    with pytest.raises(ValueError):
        ocr.preprocess(b"isto nao e imagem")


@pytest.mark.skipif(not ocr.ocr_available(), reason="Tesseract não instalado")
def test_real_ocr_on_generated_invoice_image():
    img = render_invoice_image("008812", "Cerâmica Campo Largo Blocos Ltda", "98.765.432/0001-10", date(2026, 9, 15),
                               18792.00, [("Bloco cerâmico 14x19x39", 6000, "un", 3.132)])
    r = ocr.read_invoice(img)
    f = r["fields"]
    assert f["valor"] == pytest.approx(18792.00)
    assert f["emissao"] == date(2026, 9, 15)
    assert "Campo Largo" in (f["fornecedor"] or "")


def test_graceful_fallback_when_engine_missing(monkeypatch):
    monkeypatch.setattr(ocr, "ocr_available", lambda: False)
    text, engine = ocr.extract_text(b"qualquer")
    assert (text, engine) == ("", "indisponível")
