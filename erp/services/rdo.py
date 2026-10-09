"""Diário de Obra (RDO): grava o dia e dispara os efeitos em cascata.

Salvar um RDO:
1. registra clima, mão de obra e ocorrências;
2. atualiza o avanço físico das tarefas (alimenta o VA/Curva S);
3. dá baixa no estoque pelo consumo do dia;
4. registra a inspeção das araucárias (Alerta Vermelho de embargo se violado);
5. converte Chuva Forte/problemas em impactos e RECALCULA o cronograma (nova data final).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from erp import db
from erp.services import environment, inventory, scheduling


@dataclass
class RDOInput:
    day: date
    weather: str
    temperature: float | None = None
    rain_mm: float = 0.0
    occurrences: str = ""
    labor: dict[str, int] = field(default_factory=dict)
    progress: dict[int, float] = field(default_factory=dict)
    consumption: dict[int, float] = field(default_factory=dict)
    problem_task_id: int | None = None
    problem_days: int = 0
    signed_by_contact_id: int | None = None
    araucaria: list[dict] = field(default_factory=list)
    created_by: str = ""


def save_rdo(data: RDOInput) -> dict:
    if db.query_one("SELECT id FROM rdo WHERE date = ?", (data.day.isoformat(),)):
        raise ValueError(f"Já existe RDO para {data.day:%d/%m/%Y}.")
    before = scheduling.project_summary(data.day)
    sched_before = scheduling.compute_schedule(data.day)

    rdo_id = db.execute(
        "INSERT INTO rdo(date, weather, temperature, rain_mm, occurrences, problem_task_id, problem_days, "
        "signed_by_contact_id, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (data.day.isoformat(), data.weather, data.temperature, data.rain_mm, data.occurrences,
         data.problem_task_id, data.problem_days, data.signed_by_contact_id, data.created_by, db.now_iso()),
    )
    with db.transaction() as conn:
        conn.executemany("INSERT INTO rdo_labor(rdo_id, function, quantity) VALUES (?,?,?)",
                         [(rdo_id, fn, int(q)) for fn, q in data.labor.items() if q])
    if data.progress:
        scheduling.record_progress(rdo_id, data.day, data.progress)

    consumption_errors = []
    for mat_id, qty in data.consumption.items():
        if qty and qty > 0:
            try:
                inventory.register_consumption(mat_id, qty, data.day, rdo_id=rdo_id,
                                               notes="Baixa pelo RDO", user=data.created_by)
            except ValueError as exc:
                consumption_errors.append(f"Material {mat_id}: {exc}")

    violations = []
    for insp in data.araucaria:
        ok, viol = environment.record_inspection(
            rdo_id, insp["tree_id"], data.day, insp["distance_m"], insp.get("fence_ok", True),
            insp.get("crown_damage", False), insp.get("root_damage", False), insp.get("soil_compaction", False),
            insp.get("material_stockpile", False), insp.get("notes", ""))
        if not ok:
            violations.append({"tree_id": insp["tree_id"], "violations": viol})

    problem_desc = ""
    if data.problem_task_id and data.problem_days:
        problem_desc = (data.occurrences or "Ocorrência registrada no RDO")[:200]
    impacts = scheduling.register_rdo_impacts(rdo_id, data.day, data.weather, data.problem_task_id,
                                              data.problem_days, problem_desc, sched=sched_before)
    after = scheduling.project_summary(data.day)
    return {
        "rdo_id": rdo_id,
        "impacts": impacts,
        "finish_before": before.get("projected_finish"),
        "finish_after": after.get("projected_finish"),
        "shift_days": (after["projected_finish"] - before["projected_finish"]).days if before else 0,
        "delay_vs_baseline": after.get("delay_days"),
        "embargo_risk": violations,
        "consumption_errors": consumption_errors,
    }
