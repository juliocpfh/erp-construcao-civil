"""Agrega os indicadores usados no Painel Executivo e no Flash Report."""
from __future__ import annotations

from datetime import date

from erp.services import environment, evm, inventory, scheduling


def collect_report_data(data_date: date | None = None, user: str = "-") -> dict:
    data_date = data_date or date.today()
    sched = scheduling.compute_schedule(data_date)
    summary = scheduling.project_summary(data_date, sched)
    losses = scheduling.baseline_vs_actual(data_date, sched)
    losses = losses[losses["money_lost"] > 0].sort_values("money_lost", ascending=False)
    critical = sched[sched["critical"] & (sched["progress"] < 100)].sort_values("start")
    return {
        "user": user,
        "evm": evm.evm_snapshot(data_date),
        "summary": summary,
        "curve": evm.s_curve(data_date),
        "critical": critical,
        "stock_alerts": inventory.lead_time_alerts(data_date, sched),
        "embargo_alerts": environment.active_embargo_alerts(data_date),
        "losses": losses,
        "schedule": sched,
    }
