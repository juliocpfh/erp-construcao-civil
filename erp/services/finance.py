"""Financeiro: BDI (fórmula do Acórdão TCU 2.622/2013), tributos e alertas fiscais."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from erp import db


@dataclass
class BDIParams:
    administracao_central: float = 4.0   # AC (%)
    seguro: float = 0.8                  # S (%)
    risco: float = 1.27                  # R (%)
    garantia: float = 0.8                # G (%)
    despesas_financeiras: float = 1.23   # DF (%)
    lucro: float = 7.4                   # L (%)
    pis: float = 0.65
    cofins: float = 3.0
    iss: float = 2.5                     # alíquota municipal (base de cálculo pode ter dedução)
    cprb: float = 4.5                    # INSS - Contribuição Previdenciária sobre a Receita Bruta
    reducao_beneficio: float = 0.0       # % de redução da carga tributária por benefício fiscal
    beneficios_fiscais: str = ""


def compute_bdi(p: BDIParams) -> dict:
    """BDI = [(1+AC+S+R+G)(1+DF)(1+L) / (1 - I)] - 1, com I = tributos sobre o faturamento."""
    ac, s, r, g = (p.administracao_central / 100, p.seguro / 100, p.risco / 100, p.garantia / 100)
    df, lucro = p.despesas_financeiras / 100, p.lucro / 100
    taxes = {
        "PIS": p.pis, "COFINS": p.cofins, "ISS": p.iss, "INSS (CPRB)": p.cprb,
    }
    factor = 1 - max(min(p.reducao_beneficio, 100.0), 0.0) / 100
    taxes_eff = {k: v * factor for k, v in taxes.items()}
    i_total = sum(taxes_eff.values()) / 100
    if i_total >= 1:
        raise ValueError("Tributos não podem somar 100% ou mais.")
    numerator = (1 + ac + s + r + g) * (1 + df) * (1 + lucro)
    bdi = numerator / (1 - i_total) - 1
    bdi_sem = numerator - 1
    bdi_bruto = numerator / (1 - sum(taxes.values()) / 100) - 1
    return {
        "bdi": bdi * 100,
        "bdi_sem_tributos": bdi_sem * 100,
        "parcela_tributos": (bdi - bdi_sem) * 100,
        "tributos_total": i_total * 100,
        "tributos": taxes_eff,
        "economia_beneficio": (bdi_bruto - bdi) * 100,
        "params": asdict(p),
    }


def price_with_bdi(direct_cost: float, bdi_pct: float) -> float:
    return direct_cost * (1 + bdi_pct / 100)


def load_bdi_params() -> BDIParams:
    p = BDIParams()
    for field in p.__dataclass_fields__:
        val = db.get_setting(f"bdi_{field}")
        if val is None:
            continue
        setattr(p, field, val if field == "beneficios_fiscais" else float(val))
    return p


def save_bdi_params(p: BDIParams) -> None:
    for k, v in asdict(p).items():
        db.set_setting(f"bdi_{k}", v)


SERVICE_KINDS = ("Serviço", "Material + Mão de obra")


def quote_alerts(kind: str, iss_highlighted: bool, inss_highlighted: bool) -> list[str]:
    """Cotações de serviço devem destacar ISS (LC 116/2003) e retenção de INSS 11% (Lei 8.212/91, art. 31)."""
    alerts: list[str] = []
    if kind in SERVICE_KINDS:
        if not iss_highlighted:
            alerts.append("Exigir destaque do ISS na proposta/nota (LC 116/2003) — risco de responsabilidade solidária do tomador.")
        if not inss_highlighted:
            alerts.append("Exigir destaque da retenção de 11% de INSS sobre a mão de obra (Lei 8.212/91, art. 31).")
    return alerts


def invoice_tax_alerts(kind: str, total_value: float, iss_value: float, inss_value: float) -> list[str]:
    alerts: list[str] = []
    if kind in SERVICE_KINDS:
        if not iss_value:
            alerts.append("NF de serviço sem ISS destacado.")
        if not inss_value:
            alerts.append("NF de serviço sem retenção de INSS destacada.")
        elif total_value and inss_value / total_value < 0.03:
            alerts.append("Retenção de INSS abaixo do esperado (verifique base de mão de obra).")
    return alerts


def brl(value: float | None) -> str:
    if value is None:
        return "-"
    s = f"{value:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")
