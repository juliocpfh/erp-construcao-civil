"""Cronograma: Método do Caminho Crítico (CPM), impactos do RDO e Baseline x Real.

Convenções:
- Durações em dias corridos; dependências do tipo Término-Início (FS) com ``lag``.
- ES/EF são deslocamentos (em dias) a partir do início do projeto; EF é exclusivo.
- Datas de calendário: início = início_projeto + ES; término = início_projeto + EF - 1.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from erp import db
from erp.config import HEAVY_RAIN


@dataclass
class CPMResult:
    es: int
    ef: int
    ls: int
    lf: int
    slack: int
    critical: bool


def topological_order(task_ids: list[int], preds: dict[int, list[tuple[int, int]]]) -> list[int]:
    indeg = {t: 0 for t in task_ids}
    succs: dict[int, list[int]] = defaultdict(list)
    for t in task_ids:
        for p, _lag in preds.get(t, []):
            if p not in indeg:
                raise ValueError(f"Predecessora inexistente: {p} (tarefa {t})")
            indeg[t] += 1
            succs[p].append(t)
    queue = deque(sorted(t for t, d in indeg.items() if d == 0))
    order: list[int] = []
    while queue:
        n = queue.popleft()
        order.append(n)
        for s in succs[n]:
            indeg[s] -= 1
            if indeg[s] == 0:
                queue.append(s)
    if len(order) != len(task_ids):
        raise ValueError("Ciclo detectado nas dependências do cronograma.")
    return order


def cpm(durations: dict[int, int], preds: dict[int, list[tuple[int, int]]],
        min_start: dict[int, int] | None = None, min_finish: dict[int, int] | None = None,
        fixed_start: dict[int, int] | None = None, fixed_finish: dict[int, int] | None = None) -> dict[int, CPMResult]:
    """Passagem de ida e de volta.

    ``min_start``/``min_finish`` impõem a data de status (nada pendente começa/termina no passado);
    ``fixed_start``/``fixed_finish`` fixam as datas reais (EF exclusivo) de tarefas iniciadas/concluídas.
    """
    min_start = min_start or {}
    min_finish = min_finish or {}
    fixed_start = fixed_start or {}
    fixed_finish = fixed_finish or {}
    ids = list(durations)
    order = topological_order(ids, preds)
    succs: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for t in ids:
        for p, lag in preds.get(t, []):
            succs[p].append((t, lag))

    es: dict[int, int] = {}
    ef: dict[int, int] = {}
    for t in order:
        if t in fixed_start:
            start = fixed_start[t]
        else:
            start = max([ef[p] + lag for p, lag in preds.get(t, [])] or [0])
            start = max(start, min_start.get(t, 0))
        es[t] = start
        if t in fixed_finish:
            ef[t] = max(fixed_finish[t], start + 1)
        else:
            ef[t] = max(start + max(int(durations[t]), 0), min_finish.get(t, 0))

    project_end = max(ef.values()) if ef else 0
    lf: dict[int, int] = {}
    ls: dict[int, int] = {}
    for t in reversed(order):
        finish = min([ls[s] - lag for s, lag in succs.get(t, [])] or [project_end])
        lf[t] = finish
        ls[t] = finish - (ef[t] - es[t])

    return {
        t: CPMResult(es[t], ef[t], ls[t], lf[t], ls[t] - es[t], (ls[t] - es[t]) <= 0)
        for t in ids
    }


def project_start() -> date:
    value = db.get_setting("project_start")
    return date.fromisoformat(value) if value else date.today()


def _load_network() -> tuple[pd.DataFrame, dict[int, list[tuple[int, int]]]]:
    tasks = db.query_df(
        "SELECT t.*, w.code AS wbs_code, w.name AS wbs_name, "
        "COALESCE((SELECT SUM(days) FROM schedule_impacts i WHERE i.task_id = t.id), 0) AS delay "
        "FROM tasks t LEFT JOIN wbs w ON w.id = t.wbs_id ORDER BY t.id"
    )
    deps = db.query("SELECT task_id, predecessor_id, lag FROM task_deps")
    preds: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for d in deps:
        preds[int(d["task_id"])].append((int(d["predecessor_id"]), int(d["lag"])))
    return tasks, preds


def compute_schedule(data_date: date | None = None, *, with_impacts: bool = True,
                     status_date_constraint: bool = True,
                     extra_delay: dict[int, int] | None = None) -> pd.DataFrame:
    """Calcula o cronograma projetado (com impactos do RDO e data de status)."""
    tasks, preds = _load_network()
    if tasks.empty:
        return tasks
    start = project_start()
    data_date = data_date or date.today()
    dd = (data_date - start).days

    durations: dict[int, int] = {}
    min_start: dict[int, int] = {}
    min_finish: dict[int, int] = {}
    fixed_start: dict[int, int] = {}
    fixed_finish: dict[int, int] = {}
    for row in tasks.itertuples():
        tid = int(row.id)
        dur = int(row.duration) + (int(row.delay) if with_impacts else 0) + int((extra_delay or {}).get(tid, 0))
        durations[tid] = dur
        if not status_date_constraint:
            continue
        prog = float(row.progress)
        if isinstance(row.actual_start, str) and row.actual_start:
            fixed_start[tid] = (date.fromisoformat(row.actual_start) - start).days
        if prog >= 100 and isinstance(row.actual_finish, str) and row.actual_finish:
            fixed_finish[tid] = (date.fromisoformat(row.actual_finish) - start).days + 1
        elif dd > 0:
            if prog <= 0:
                min_start[tid] = dd  # não iniciada: não pode começar no passado
            else:
                remaining = math.ceil(dur * (1 - prog / 100.0))
                min_finish[tid] = dd + remaining
    res = cpm(durations, preds, min_start, min_finish, fixed_start, fixed_finish)

    tasks["eff_duration"] = tasks["id"].map(durations)
    for attr in ("es", "ef", "ls", "lf", "slack", "critical"):
        tasks[attr] = tasks["id"].map(lambda t, a=attr: getattr(res[int(t)], a))
    tasks["start"] = tasks["es"].map(lambda d: start + timedelta(days=int(d)))
    tasks["finish"] = tasks["ef"].map(lambda d: start + timedelta(days=int(d) - 1))
    tasks["baseline_start"] = pd.to_datetime(tasks["baseline_start"]).dt.date
    tasks["baseline_finish"] = pd.to_datetime(tasks["baseline_finish"]).dt.date
    tasks["finish_variance"] = (pd.to_datetime(tasks["finish"]) - pd.to_datetime(tasks["baseline_finish"])).dt.days
    codes = dict(zip(tasks["id"].astype(int), tasks["code"]))
    tasks["predecessors"] = tasks["id"].map(
        lambda t: ", ".join(sorted(codes[p] for p, _ in preds.get(int(t), [])))
    )
    tasks["critical"] = tasks["critical"].astype(bool)
    return tasks


def baseline_schedule() -> pd.DataFrame:
    """CPM sobre as durações originais, sem impactos (linha de base congelada)."""
    return compute_schedule(with_impacts=False, status_date_constraint=False)


def project_summary(data_date: date | None = None, sched: pd.DataFrame | None = None) -> dict:
    sched = sched if sched is not None else compute_schedule(data_date)
    if sched.empty:
        return {}
    baseline_finish = max(sched["baseline_finish"])
    projected_finish = max(sched["finish"])
    delay = (projected_finish - baseline_finish).days
    daily_indirect = float(db.get_setting("daily_indirect_cost", "0") or 0)
    return {
        "start": project_start(),
        "baseline_finish": baseline_finish,
        "projected_finish": projected_finish,
        "delay_days": delay,
        "delay_cost": max(delay, 0) * daily_indirect,
        "critical_count": int(sched["critical"].sum()),
        "impact_days": int(sched["delay"].sum()),
    }


def active_tasks_on(day: date, sched: pd.DataFrame) -> pd.DataFrame:
    mask = (sched["start"] <= day) & (sched["finish"] >= day) & (sched["progress"] < 100)
    return sched[mask]


def record_progress(rdo_id: int, day: date, progress: dict[int, float]) -> None:
    """Registra o avanço físico informado no RDO e as datas reais de início/término."""
    with db.transaction() as conn:
        for tid, pct in progress.items():
            pct = max(0.0, min(float(pct), 100.0))
            conn.execute("INSERT OR REPLACE INTO rdo_progress(rdo_id, task_id, progress) VALUES (?,?,?)",
                         (rdo_id, tid, pct))
            conn.execute("UPDATE tasks SET progress = ? WHERE id = ?", (pct, tid))
            if pct > 0:
                conn.execute("UPDATE tasks SET actual_start = ? WHERE id = ? AND (actual_start IS NULL OR actual_start > ?)",
                             (day.isoformat(), tid, day.isoformat()))
            conn.execute("UPDATE tasks SET actual_finish = ? WHERE id = ?",
                         (day.isoformat() if pct >= 100 else None, tid))


def rdo_impacts(day: date, weather: str, problem_task_id: int | None = None, problem_days: int = 0,
                problem_desc: str = "", sched: pd.DataFrame | None = None) -> list[dict]:
    """Regra de impacto do RDO (sem gravar).

    - Chuva Forte: +1 dia para cada tarefa externa (a céu aberto) ativa no dia.
    - Problema informado em uma tarefa: +N dias naquela tarefa.
    """
    impacts: list[dict] = []
    if weather == HEAVY_RAIN:
        sched = sched if sched is not None else compute_schedule(day)
        for row in active_tasks_on(day, sched).itertuples():
            if int(row.outdoor):
                impacts.append({"task_id": int(row.id), "code": row.code, "days": 1,
                                "reason": f"Chuva Forte em {day:%d/%m/%Y} - {row.code}"})
    if problem_task_id and problem_days:
        impacts.append({"task_id": int(problem_task_id), "code": None, "days": int(problem_days),
                        "reason": problem_desc or f"Ocorrência no RDO de {day:%d/%m/%Y}"})
    return impacts


def preview_rdo_impact(day: date, weather: str, problem_task_id: int | None = None, problem_days: int = 0) -> dict:
    """Recalcula em tempo real (sem gravar) a data final projetada caso o RDO seja salvo."""
    current = compute_schedule(day)
    impacts = rdo_impacts(day, weather, problem_task_id, problem_days, sched=current)
    extra: dict[int, int] = defaultdict(int)
    for i in impacts:
        extra[i["task_id"]] += i["days"]
    new = compute_schedule(day, extra_delay=extra) if extra else current
    before, after = max(current["finish"]), max(new["finish"])
    crit_hit = [i for i in impacts if bool(current.loc[current["id"] == i["task_id"], "critical"].any())]
    return {"impacts": impacts, "critical_impacts": crit_hit, "finish_before": before, "finish_after": after,
            "shift_days": (after - before).days, "baseline_finish": max(current["baseline_finish"])}


def register_rdo_impacts(rdo_id: int, day: date, weather: str, problem_task_id: int | None = None,
                         problem_days: int = 0, problem_desc: str = "",
                         sched: pd.DataFrame | None = None) -> list[dict]:
    """Converte o RDO em impactos no cronograma (recalculo automático).

    - Chuva Forte: +1 dia para cada tarefa externa (a céu aberto) ativa no dia.
    - Problema informado em uma tarefa: +N dias naquela tarefa.
    """
    impacts = rdo_impacts(day, weather, problem_task_id, problem_days, problem_desc, sched)
    if impacts:
        with db.transaction() as conn:
            conn.executemany(
                "INSERT INTO schedule_impacts(rdo_id, task_id, days, reason, created_at) VALUES (?,?,?,?,?)",
                [(rdo_id, i["task_id"], i["days"], i["reason"], db.now_iso()) for i in impacts],
            )
    return impacts


def freeze_baseline() -> None:
    """Grava as datas do CPM original como linha de base (Baseline)."""
    tasks, preds = _load_network()
    durations = {int(r.id): int(r.duration) for r in tasks.itertuples()}
    res = cpm(durations, preds)
    start = project_start()
    with db.transaction() as conn:
        conn.executemany(
            "UPDATE tasks SET baseline_start = ?, baseline_finish = ? WHERE id = ?",
            [((start + timedelta(days=r.es)).isoformat(), (start + timedelta(days=r.ef - 1)).isoformat(), t)
             for t, r in res.items()],
        )


def baseline_vs_actual(data_date: date | None = None, sched: pd.DataFrame | None = None) -> pd.DataFrame:
    """Onde se perdeu tempo e dinheiro: por tarefa, desvio de prazo e de custo."""
    sched = sched if sched is not None else compute_schedule(data_date)
    costs = db.query_df(
        "SELECT task_id, SUM(total_value) AS actual_cost FROM invoices WHERE status = 'Aprovada' "
        "AND task_id IS NOT NULL GROUP BY task_id"
    )
    df = sched.merge(costs, how="left", left_on="id", right_on="task_id")
    df["actual_cost"] = df["actual_cost"].fillna(0.0)
    df["earned_value"] = df["baseline_cost"] * df["progress"] / 100.0
    df["cost_variance"] = df["earned_value"] - df["actual_cost"]  # negativo = perdeu dinheiro
    daily_indirect = float(db.get_setting("daily_indirect_cost", "0") or 0)
    # dias perdidos DENTRO da tarefa (duração real/projetada - duração planejada), só para iniciadas
    df["lost_days"] = df.apply(
        lambda r: max((r["finish"] - r["start"]).days + 1 - int(r["duration"]), 0) if r["progress"] > 0 else 0, axis=1
    )
    df["delay_cost"] = df.apply(lambda r: r["lost_days"] * daily_indirect if r["critical"] else 0.0, axis=1)
    df["money_lost"] = (-df["cost_variance"]).clip(lower=0) + df["delay_cost"]
    return df[[
        "id", "code", "name", "wbs_name", "critical", "baseline_start", "baseline_finish", "start", "finish",
        "finish_variance", "delay", "lost_days", "baseline_cost", "progress", "earned_value", "actual_cost",
        "cost_variance", "delay_cost", "money_lost",
    ]]
