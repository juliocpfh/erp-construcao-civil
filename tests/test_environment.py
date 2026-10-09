from erp import db
from erp.services import environment
from erp.services.rdo import RDOInput, save_rdo
from tests.conftest import TODAY

TREE = {"dap_cm": 50, "crown_radius_m": 4.0}


def test_protection_radius_uses_max_of_crown_and_dap():
    assert environment.protection_radius(50, 4.0, 12) == 6.0
    assert environment.protection_radius(20, 5.0, 12) == 5.0


def test_compliant_inspection(empty_db):
    ok, viol = environment.evaluate_inspection(TREE, 8.0, True, False, False, False, False)
    assert ok and viol == []


def test_violations_detected(empty_db):
    ok, viol = environment.evaluate_inspection(TREE, 3.0, False, True, False, False, True)
    assert not ok
    assert len(viol) == 4
    assert "raio de proteção 6.0 m" in viol[0]


def test_seeded_active_embargo_alert(seeded):
    alerts = environment.active_embargo_alerts(TODAY)
    assert len(alerts) == 1 and alerts[0]["tag"] == "ARA-02"
    environment.resolve_alert(alerts[0]["id"])
    assert environment.active_embargo_alerts(TODAY) == []


def test_rdo_with_araucaria_violation_raises_red_alert(seeded):
    tree = db.query_one("SELECT id FROM araucaria_trees WHERE tag = 'ARA-03'")
    result = save_rdo(RDOInput(day=TODAY, weather="Nublado", araucaria=[
        {"tree_id": tree["id"], "distance_m": 2.0, "fence_ok": True, "root_damage": True}]))
    assert result["embargo_risk"]
    tags = {a["tag"] for a in environment.active_embargo_alerts(TODAY)}
    assert "ARA-03" in tags
