"""Gerenciamento do Valor Agregado (PMI/PMBOK): VP, VA, CR, IDC, IDP e Curva S.

- VP (Valor Planejado / PV): custo da linha de base distribuído linearmente no prazo planejado.
- VA (Valor Agregado / EV): custo da linha de base x % físico executado (informado no RDO).
- CR (Custo Real / AC): soma das Notas Fiscais APROVADAS.
- IDC (CPI) = VA / CR      IDP (SPI) = VA / VP
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from erp import db
from erp.services.scheduling import project_start


def _planned_fraction(day: pd.Timestamp, start: pd.Series, finish: pd.Series) -> pd.Series:
    total = (finish - start).dt.days + 1
    elapsed = (day - start).dt.days + 1
    return (elapsed / total.replace(0, 1)).clip(lower=0, upper=1)


def _tasks() -> pd.DataFrame:
    df = db.query_df("SELECT id, baseline_start, baseline_finish, baseline_cost, progress FROM tasks")
    df["baseline_start"] = pd.to_datetime(df["baseline_start"])
    df["baseline_finish"] = pd.to_datetime(df["baseline_finish"])
    return df


def _progress_history() -> pd.DataFrame:
    df = db.query_df(
        "SELECT r.date, p.task_id, p.progress FROM rdo_progress p JOIN rdo r ON r.id = p.rdo_id ORDER BY r.date"
    )
    df["date"] = pd.to_datetime(df["date"])
    return df


def _approved_costs() -> pd.DataFrame:
    df = db.query_df("SELECT issue_date, total_value FROM invoices WHERE status = 'Aprovada'")
    df["issue_date"] = pd.to_datetime(df["issue_date"])
    return df


def planned_value(day: date, tasks: pd.DataFrame | None = None) -> float:
    tasks = tasks if tasks is not None else _tasks()
    frac = _planned_fraction(pd.Timestamp(day), tasks["baseline_start"], tasks["baseline_finish"])
    return float((tasks["baseline_cost"] * frac).sum())


def earned_value(day: date | None = None, tasks: pd.DataFrame | None = None,
                 history: pd.DataFrame | None = None) -> float:
    tasks = tasks if tasks is not None else _tasks()
    if day is None or day >= date.today():
        return float((tasks["baseline_cost"] * tasks["progress"] / 100.0).sum())
    history = history if history is not None else _progress_history()
    upto = history[history["date"] <= pd.Timestamp(day)]
    if upto.empty:
        return 0.0
    latest = upto.groupby("task_id")["progress"].last()
    costs = tasks.set_index("id")["baseline_cost"]
    return float((costs.reindex(latest.index).fillna(0) * latest / 100.0).sum())


def actual_cost(day: date | None = None, costs: pd.DataFrame | None = None) -> float:
    costs = costs if costs is not None else _approved_costs()
    if day is not None:
        costs = costs[costs["issue_date"] <= pd.Timestamp(day)]
    return float(costs["total_value"].sum())


def safe_ratio(num: float, den: float) -> float:
    return float(num / den) if den else 0.0


def evm_snapshot(day: date | None = None) -> dict:
    day = day or date.today()
    tasks = _tasks()
    pv = planned_value(day, tasks)
    ev = earned_value(day, tasks)
    ac = actual_cost(day)
    bac = float(tasks["baseline_cost"].sum())
    cpi = safe_ratio(ev, ac)
    spi = safe_ratio(ev, pv)
    eac = bac / cpi if cpi else bac
    return {
        "data_date": day,
        "BAC": bac, "VP": pv, "VA": ev, "CR": ac,
        "IDC": cpi, "IDP": spi,
        "VC": ev - ac,           # variação de custo
        "VPr": ev - pv,          # variação de prazo (em R$)
        "EAC": eac,              # estimativa no término
        "VAC": bac - eac,        # variação no término
        "pct_planned": safe_ratio(pv, bac) * 100,
        "pct_earned": safe_ratio(ev, bac) * 100,
    }


def s_curve(day: date | None = None, freq: str = "W-MON") -> pd.DataFrame:
    """Série temporal acumulada VP x VA x CR. VP segue até o fim da linha de base."""
    day = day or date.today()
    tasks = _tasks()
    if tasks.empty:
        return pd.DataFrame(columns=["date", "VP", "VA", "CR"])
    history = _progress_history()
    costs = _approved_costs()
    start = pd.Timestamp(project_start())
    end = max(tasks["baseline_finish"].max(), pd.Timestamp(day))
    dates = list(pd.date_range(start, end, freq=freq))
    if pd.Timestamp(day) not in dates:
        dates.append(pd.Timestamp(day))
    dates = sorted(set(dates + [end]))
    rows = []
    for d in dates:
        pv = planned_value(d.date(), tasks)
        if d <= pd.Timestamp(day):
            ev = earned_value(d.date() if d < pd.Timestamp(day) else None, tasks, history)
            ac = actual_cost(d.date(), costs)
        else:
            ev = ac = np.nan
        rows.append({"date": d, "VP": pv, "VA": ev, "CR": ac})
    return pd.DataFrame(rows)


def performance_label(index: float) -> str:
    if index >= 1.0:
        return "Dentro/abaixo do planejado"
    if index >= 0.9:
        return "Atenção"
    return "Crítico"
