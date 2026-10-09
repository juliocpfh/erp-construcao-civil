import pytest

from erp import db
from erp.services import evm, finance, inventory
from tests.conftest import TODAY


def test_bdi_tcu_formula():
    p = finance.BDIParams(administracao_central=4, seguro=0.8, risco=1.27, garantia=0.8, despesas_financeiras=1.23,
                          lucro=7.4, pis=0.65, cofins=3.0, iss=2.5, cprb=4.5)
    r = finance.compute_bdi(p)
    num = (1 + .04 + .008 + .0127 + .008) * 1.0123 * 1.074
    assert r["bdi"] == pytest.approx((num / (1 - .1065) - 1) * 100, rel=1e-9)
    assert r["bdi_sem_tributos"] == pytest.approx((num - 1) * 100)
    assert r["parcela_tributos"] == pytest.approx(r["bdi"] - r["bdi_sem_tributos"])
    assert r["tributos_total"] == pytest.approx(10.65)


def test_bdi_tax_benefit_reduces_bdi():
    base = finance.compute_bdi(finance.BDIParams())
    benef = finance.compute_bdi(finance.BDIParams(reducao_beneficio=50))
    assert benef["bdi"] < base["bdi"]
    assert benef["economia_beneficio"] == pytest.approx(base["bdi"] - benef["bdi"])
    with pytest.raises(ValueError):
        finance.compute_bdi(finance.BDIParams(pis=50, cofins=50))


def test_quote_alerts_require_iss_inss_for_services():
    assert len(finance.quote_alerts("Serviço", False, False)) == 2
    assert finance.quote_alerts("Serviço", True, True) == []
    assert finance.quote_alerts("Material", False, False) == []
    assert any("INSS" in a for a in finance.invoice_tax_alerts("Serviço", 1000, 25, 0))


def test_brl_format():
    assert finance.brl(1234567.891) == "R$ 1.234.567,89"


def test_evm_indices(seeded):
    s = evm.evm_snapshot(TODAY)
    assert s["BAC"] > 10_000_000
    assert 0 < s["VA"] <= s["BAC"]
    assert s["IDC"] == pytest.approx(s["VA"] / s["CR"])
    assert s["IDP"] == pytest.approx(s["VA"] / s["VP"])
    assert s["IDP"] < 1  # obra atrasada na simulação


def test_approved_invoice_increases_actual_cost(seeded):
    before = evm.evm_snapshot(TODAY)
    inv = db.query_one("SELECT id, total_value FROM invoices WHERE status = 'Pendente' AND issue_date <= ? LIMIT 1",
                       (TODAY.isoformat(),))
    assert inv
    inventory.approve_invoice(inv["id"], "admin")
    after = evm.evm_snapshot(TODAY)
    assert after["CR"] == pytest.approx(before["CR"] + inv["total_value"])
    assert after["IDC"] < before["IDC"]


def test_s_curve(seeded):
    curve = evm.s_curve(TODAY)
    assert list(curve.columns) == ["date", "VP", "VA", "CR"]
    assert curve["VP"].is_monotonic_increasing
    past = curve.dropna()
    assert past["CR"].is_monotonic_increasing
    assert curve["VP"].iloc[-1] == pytest.approx(evm.evm_snapshot(TODAY)["BAC"], rel=1e-6)
