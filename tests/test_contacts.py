from pathlib import Path

from erp import db
from erp.services import contacts

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "contatos_obra.vcf"


def test_parse_vcf_versions_and_quoted_printable():
    cards = contacts.parse_vcf(SAMPLE.read_bytes())
    assert len(cards) == 7
    names = [c["name"] for c in cards]
    assert "Otávio Araújo" in names  # vCard 2.1 quoted-printable UTF-8
    ricardo = next(c for c in cards if c["name"] == "Ricardo Benghi")  # vCard 4.0 tel:uri
    assert ricardo["phone"] == "+5541996677889"
    assert ricardo["email"] == "ricardo@canteiroservicos.com.br"


def test_folded_lines_and_n_fallback():
    vcf = "BEGIN:VCARD\r\nVERSION:3.0\r\nN:Silva;Maria;;;\r\nEMAIL:maria@\r\n exemplo.com\r\nTEL:41 3333-4444\r\nEND:VCARD\r\n"
    cards = contacts.parse_vcf(vcf)
    assert cards[0]["name"] == "Maria Silva"
    assert cards[0]["email"] == "maria@exemplo.com"
    assert contacts.format_phone(cards[0]["phone"]) == "(41) 3333-4444"


def test_import_links_invoices_and_builds_timeline(seeded):
    unlinked = db.query_one("SELECT COUNT(*) n FROM invoices WHERE supplier_name = 'Alvenaria Pinhais Empreiteira Ltda' "
                            "AND supplier_contact_id IS NULL")["n"]
    assert unlinked > 0
    result = contacts.import_contacts(contacts.parse_vcf(SAMPLE.read_bytes()))
    assert result["created"] >= 5
    assert result["updated"] >= 1  # Patrícia Hoffmann já existia
    assert result["linked_invoices"] >= unlinked
    gilmar = db.query_one("SELECT id FROM contacts WHERE name = 'Gilmar Ostrowski'")
    events = contacts.contact_timeline(gilmar["id"])
    assert any(e["type"] == "NF emitida" for e in events)


def test_timeline_of_site_team(seeded):
    mestre = db.query_one("SELECT id FROM contacts WHERE title = 'Mestre de Obras'")
    events = contacts.contact_timeline(mestre["id"])
    types = {e["type"] for e in events}
    assert {"Tarefa gerenciada", "RDO assinado"} <= types
