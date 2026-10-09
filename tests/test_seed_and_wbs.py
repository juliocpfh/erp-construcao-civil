from erp import auth, db
from erp.services import wbs
from erp.storage import load_media


def test_seed_volume(seeded):
    assert seeded["tasks"] == 44
    assert seeded["rdos"] > 200
    assert seeded["invoices"] > 60
    assert seeded["photos"] > 30
    rain = db.query_one("SELECT COUNT(*) n FROM rdo WHERE weather = 'Chuva Forte'")["n"]
    assert rain >= 5
    assert db.query_one("SELECT COUNT(*) n FROM schedule_impacts")["n"] >= 5
    assert db.query_one("SELECT COUNT(*) n FROM legal_docs")["n"] >= 10
    cats = {r["category"] for r in db.query("SELECT DISTINCT category FROM legal_docs")}
    assert cats == {"Copel", "Sanepar", "Bombeiros", "Calçadas", "ABNT"}
    folders = {r["folder"] for r in db.query("SELECT DISTINCT folder FROM ged_files")}
    assert folders == {"Projetos", "Listas de Materiais", "Laudos/Licenças"}
    exts = {r["extension"] for r in db.query("SELECT DISTINCT extension FROM ged_files")}
    assert {"pdf", "dwg", "ifc"} <= exts


def test_seed_users(seeded):
    assert auth.authenticate("admin", "admin123")["role"] == "Administrador"
    assert auth.authenticate("almoxarife", "campo123")["role"] == "Almoxarife"
    assert auth.authenticate("visualizador", "visual123")["role"] == "Visualizador"
    assert auth.authenticate("fiscal.banco", "Prov@2026")["must_change_password"] == 1
    assert auth.authenticate("almox.noturno", "campo456") is None  # inativo


def test_seed_media_readable(seeded):
    photo = db.query_one("SELECT media_key FROM photos LIMIT 1")
    assert load_media(photo["media_key"])[:2] == b"\xff\xd8"  # JPEG
    nf = db.query_one("SELECT nf_media_key FROM invoices WHERE nf_media_key IS NOT NULL LIMIT 1")
    assert load_media(nf["nf_media_key"])[:4] == b"\x89PNG"


def test_seed_is_idempotent(seeded):
    from erp.seed import seed_database

    assert seed_database() == {"skipped": True}


def test_wbs_rollup_and_views(seeded):
    df = wbs.load_wbs()
    root = df[df["level"] == 0].iloc[0]
    assert root["budget"] == df[df["level"] == 1]["budget"].sum()
    assert 0 < root["progress"] < 100
    dot = wbs.graphviz_tree(df, 2).source
    assert "1.3" in dot and "->" in dot
    table = wbs.indented_table(df)
    assert table["EAP"].iloc[0].startswith("■ 1")
    assert "└─" in table["EAP"].iloc[1]
    statuses = set(df["status"])
    assert {"Concluído", "Em Andamento", "A Fazer"} <= statuses


def test_wbs_add_deliverable_numbering(seeded):
    parent = db.query_one("SELECT id FROM wbs WHERE code = '1.3'")
    new_id = wbs.add_deliverable(parent["id"], "Reforço estrutural")
    assert db.query_one("SELECT code FROM wbs WHERE id = ?", (new_id,))["code"] == "1.3.4"
    wbs.set_status(new_id, "Em Andamento")
    assert db.query_one("SELECT status FROM wbs WHERE id = ?", (new_id,))["status"] == "Em Andamento"
