from datetime import date, timedelta

import pytest

from erp import db
from erp.services import scheduling
from erp.services.rdo import RDOInput, save_rdo
from tests.conftest import TODAY


def test_cpm_classic_network():
    # A(3) -> B(4) -> D(2); A -> C(2) -> D ; caminho crítico A-B-D = 9
    dur = {1: 3, 2: 4, 3: 2, 4: 2}
    preds = {2: [(1, 0)], 3: [(1, 0)], 4: [(2, 0), (3, 0)]}
    r = scheduling.cpm(dur, preds)
    assert max(x.ef for x in r.values()) == 9
    assert [t for t, x in r.items() if x.critical] == [1, 2, 4]
    assert r[3].slack == 2
    assert (r[3].es, r[3].ef, r[3].ls, r[3].lf) == (3, 5, 5, 7)


def test_cpm_lag_and_cycle():
    r = scheduling.cpm({1: 2, 2: 2}, {2: [(1, 3)]})
    assert r[2].es == 5
    with pytest.raises(ValueError):
        scheduling.cpm({1: 1, 2: 1}, {1: [(2, 0)], 2: [(1, 0)]})


def test_status_date_constraint():
    r = scheduling.cpm({1: 5}, {}, min_start={1: 10})
    assert (r[1].es, r[1].ef) == (10, 15)


def test_seeded_schedule_has_critical_path_and_delay(seeded):
    sched = scheduling.compute_schedule(TODAY)
    summary = scheduling.project_summary(TODAY, sched)
    assert sched["critical"].any()
    assert summary["projected_finish"] > summary["baseline_finish"]  # atrasos por chuva/ocorrências
    # a última tarefa (Habite-se) é sempre crítica
    assert bool(sched.loc[sched["code"] == "EN3", "critical"].iloc[0])


def _free_day(sched):
    day = TODAY
    while db.query_one("SELECT 1 FROM rdo WHERE date = ?", (day.isoformat(),)):
        day += timedelta(days=1)
    return day


def test_heavy_rain_on_critical_outdoor_task_recalculates_finish(seeded):
    sched = scheduling.compute_schedule(TODAY)
    day = _free_day(sched)
    active = scheduling.active_tasks_on(day, scheduling.compute_schedule(day))
    crit_outdoor = active[(active["critical"]) & (active["outdoor"] == 1)]
    assert not crit_outdoor.empty, "cenário de simulação deve ter estrutura (externa e crítica) em execução"
    preview = scheduling.preview_rdo_impact(day, "Chuva Forte")
    assert preview["shift_days"] >= 1
    result = save_rdo(RDOInput(day=day, weather="Chuva Forte", rain_mm=60, occurrences="Temporal"))
    assert result["impacts"]
    assert result["finish_after"] == preview["finish_after"]
    assert result["shift_days"] >= 1
    assert db.query_one("SELECT COUNT(*) n FROM schedule_impacts WHERE rdo_id = ?", (result["rdo_id"],))["n"] >= 1


def test_sunny_day_does_not_change_finish(seeded):
    day = _free_day(None)
    result = save_rdo(RDOInput(day=day, weather="Ensolarado"))
    assert result["impacts"] == [] and result["shift_days"] == 0


def test_problem_on_critical_task(seeded):
    day = _free_day(None)
    sched = scheduling.compute_schedule(day)
    crit = sched[(sched["critical"]) & (sched["progress"] < 100)].iloc[0]
    result = save_rdo(RDOInput(day=day, weather="Nublado", problem_task_id=int(crit["id"]), problem_days=3,
                               occurrences="Falta de material"))
    assert result["shift_days"] == 3


def test_duplicate_rdo_rejected(seeded):
    existing = db.query_one("SELECT date FROM rdo LIMIT 1")["date"]
    with pytest.raises(ValueError):
        save_rdo(RDOInput(day=date.fromisoformat(existing), weather="Nublado"))


def test_progress_updates_actual_dates(seeded):
    day = _free_day(None)
    sched = scheduling.compute_schedule(day)
    task = sched[sched["progress"] == 0].iloc[0]
    save_rdo(RDOInput(day=day, weather="Nublado", progress={int(task["id"]): 10}))
    row = db.query_one("SELECT progress, actual_start FROM tasks WHERE id = ?", (int(task["id"]),))
    assert row["progress"] == 10 and row["actual_start"] == day.isoformat()


def test_baseline_vs_actual_shows_losses(seeded):
    df = scheduling.baseline_vs_actual(TODAY)
    assert (df["money_lost"] > 0).any()
    assert {"cost_variance", "delay_cost", "lost_days"} <= set(df.columns)
