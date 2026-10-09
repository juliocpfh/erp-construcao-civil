from datetime import timedelta

import pytest

from erp import db
from erp.services import inventory
from tests.conftest import TODAY


def test_invoice_approval_feeds_stock(seeded):
    inv = db.query_one("SELECT i.id FROM invoices i JOIN invoice_items it ON it.invoice_id = i.id "
                       "WHERE i.status = 'Pendente' LIMIT 1")
    item = db.query_one("SELECT material_id, quantity FROM invoice_items WHERE invoice_id = ?", (inv["id"],))
    before = inventory.material_stock(item["material_id"])
    inventory.approve_invoice(inv["id"], "almoxarife")
    assert inventory.material_stock(item["material_id"]) == pytest.approx(before + item["quantity"])
    # aprovar de novo não duplica a entrada
    inventory.approve_invoice(inv["id"], "almoxarife")
    assert inventory.material_stock(item["material_id"]) == pytest.approx(before + item["quantity"])


def test_rejected_invoice_does_not_feed_stock(seeded):
    inv = db.query_one("SELECT i.id FROM invoices i JOIN invoice_items it ON it.invoice_id = i.id "
                       "WHERE i.status = 'Pendente' LIMIT 1")
    item = db.query_one("SELECT material_id FROM invoice_items WHERE invoice_id = ?", (inv["id"],))
    before = inventory.material_stock(item["material_id"])
    inventory.reject_invoice(inv["id"], "admin")
    assert inventory.material_stock(item["material_id"]) == before


def test_consumption_reduces_stock_and_blocks_negative(seeded):
    mat = db.query_one("SELECT id FROM materials WHERE code = 'M03'")
    before = inventory.material_stock(mat["id"])
    inventory.register_consumption(mat["id"], 10, TODAY)
    assert inventory.material_stock(mat["id"]) == pytest.approx(before - 10)
    with pytest.raises(ValueError):
        inventory.register_consumption(mat["id"], before * 10 + 1, TODAY)
    with pytest.raises(ValueError):
        inventory.register_consumption(mat["id"], 0, TODAY)


def test_simulation_stock_never_negative(seeded):
    levels = inventory.stock_levels()
    assert (levels["stock"] >= -1e-6).all(), levels[levels["stock"] < 0]


def test_lead_time_alert_for_upcoming_critical_tasks(seeded):
    alerts = inventory.lead_time_alerts(TODAY)
    assert not alerts.empty
    assert (alerts["stock"] < alerts["required"]).all()


def test_lead_time_alert_clears_when_stock_arrives(seeded):
    alerts = inventory.lead_time_alerts(TODAY)
    row = alerts.iloc[0]
    inventory.add_movement(int(row["material_id"]), float(row["shortfall"]) + 1, TODAY - timedelta(days=1),
                           "ENTRADA", "Ajuste")
    after = inventory.lead_time_alerts(TODAY)
    assert int(row["material_id"]) not in set(after.get("material_id", []))
