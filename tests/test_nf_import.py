"""Materiais cadastrados automaticamente a partir dos itens da NF (XML da NF-e, OCR ou texto)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from erp import db
from erp.services import inventory, nf_import, ocr

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data"


def _invoice(supplier="Depósito", cnpj="12.345.678/0001-95") -> int:
    return db.execute("INSERT INTO invoices(number, supplier_name, supplier_cnpj, issue_date, total_value, kind, created_at) "
                      "VALUES ('1', ?, ?, '2026-10-01', 100, 'Material', ?)", (supplier, cnpj, db.now_iso()))


def test_parse_nfe_xml():
    parsed = nf_import.parse_nfe_xml((SAMPLE / "nfe_exemplo.xml").read_bytes())
    f = parsed["fields"]
    assert f["fornecedor"] == "Deposito Curitibano de Materiais Ltda" and f["cnpj"] == "12.345.678/0001-95"
    assert f["numero"] == "4521" and f["valor"] == 8156.0 and f["emissao"] == date(2026, 9, 28)
    assert [(i.supplier_code, i.unit, i.quantity, i.unit_price) for i in parsed["items"]] == [
        ("CIM50", "sc", 120.0, 38.5), ("ARG-AC3", "sc", 80.0, 34.9), ("REJ-CZ", "un", 60.0, 12.4)]


def test_parse_items_from_text():
    text = ("DESCRIÇÃO QTD UN VL UNIT\nBloco cerâmico 14x19x39 6.000,0 un 3,13\n"
            "001234 CIMENTO CP-II 50KG 25232910 000 5102 SC 120 38,50 4.620,00\nVALOR TOTAL DA NOTA: R$ 18.792,00\n")
    items = nf_import.parse_items_text(text)
    assert [(i.description, i.quantity, i.unit, i.unit_price) for i in items] == [
        ("Bloco cerâmico 14x19x39", 6000.0, "un", 3.13), ("CIMENTO CP-II 50KG", 120.0, "sc", 38.5)]
    assert items[1].supplier_code == "001234"


def test_ocr_of_sample_invoice_reads_items():
    if not ocr.ocr_available():
        return
    res = ocr.read_invoice((SAMPLE / "nf_exemplo.png").read_bytes())
    assert any("bloco" in i["description"].lower() and i["quantity"] == 6000 for i in res["items"])


def test_new_materials_created_and_reused(empty_db):
    parsed = nf_import.parse_nfe_xml((SAMPLE / "nfe_exemplo.xml").read_bytes())
    cnpj = parsed["fields"]["cnpj"]
    inv = _invoice(cnpj=cnpj)
    reg = nf_import.register_items(inv, [i.as_dict() for i in parsed["items"]], cnpj)
    assert reg == {"created": 3, "linked": 0, "created_ids": reg["created_ids"]}
    mats = db.query("SELECT code, name, unit, unit_cost, origin FROM materials ORDER BY code")
    assert [(m["code"], m["unit"], m["origin"]) for m in mats] == [("M01", "sc", "nf"), ("M02", "sc", "nf"), ("M03", "un", "nf")]
    assert mats[0]["name"] == "CIMENTO CP-II 50 KG" and mats[0]["unit_cost"] == 38.5

    # aprovação dá entrada no estoque dos materiais recém-criados
    inventory.approve_invoice(inv, "teste")
    assert inventory.material_stock(reg["created_ids"][0]) == 120

    # 2ª NF do mesmo fornecedor: mesmo código de produto, descrição diferente -> reaproveita
    items2 = [{"description": "Cimento CP II-32 saco 50kg", "quantity": 10, "unit": "sc", "unit_price": 39.9,
               "supplier_code": "CIM50"}]
    reg2 = nf_import.register_items(_invoice(cnpj=cnpj), items2, cnpj)
    assert reg2["created"] == 0 and reg2["linked"] == 1
    assert db.query_one("SELECT unit_cost FROM materials WHERE code = 'M01'")["unit_cost"] == 39.9  # preço atualizado


def test_matches_existing_material_by_similar_description(empty_db):
    mid = db.execute("INSERT INTO materials(code, name, unit, unit_cost) VALUES ('M01', 'Bloco cerâmico 14x19x39', 'un', 2.9)")
    item = {"description": "BLOCO CERAMICO 14X19X39", "quantity": 100, "unit": "un", "unit_price": 3.1}
    assert nf_import.match_material(item)[0] == mid
    other = {"description": "Tinta acrílica branca 18L", "quantity": 2, "unit": "gl", "unit_price": 400}
    assert nf_import.match_material(other) == (None, "")
    reg = nf_import.register_items(_invoice(), [item, other], None)
    assert reg["created"] == 1 and reg["linked"] == 1
    assert db.query_one("SELECT COUNT(*) AS n FROM materials")["n"] == 2
