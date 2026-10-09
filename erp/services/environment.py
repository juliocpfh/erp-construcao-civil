"""Proteção à Araucária (Araucaria angustifolia) e conformidade ambiental no RDO.

Critério adotado (configurável): raio de proteção = max(raio da copa, 12 x DAP),
com DAP (diâmetro à altura do peito) em metros — referência de zona crítica de raízes.
A espécie consta na Lista Nacional de Espécies Ameaçadas (Portaria MMA 443/2014,
atualizada pela Portaria MMA 148/2022) e sua supressão/dano é
vedado sem autorização (Lei 11.428/2006 - Mata Atlântica), sujeitando a obra a embargo.
"""
from __future__ import annotations

from datetime import date, timedelta

from erp import db

CHECKLIST = {
    "fence_ok": "Cercamento de proteção íntegro no raio crítico",
    "crown_damage": "Dano à copa / galhos (poda não autorizada, choque de equipamento)",
    "root_damage": "Corte ou exposição de raízes",
    "soil_compaction": "Compactação do solo / tráfego de máquinas na zona protegida",
    "material_stockpile": "Depósito de materiais/entulho na zona protegida",
}


def protection_radius(dap_cm: float, crown_radius_m: float, factor: float | None = None) -> float:
    factor = factor if factor is not None else float(db.get_setting("araucaria_dap_factor", "12") or 12)
    return round(max(crown_radius_m, factor * dap_cm / 100.0), 2)


def evaluate_inspection(tree: dict, distance_m: float, fence_ok: bool, crown_damage: bool,
                        root_damage: bool, soil_compaction: bool, material_stockpile: bool) -> tuple[bool, list[str]]:
    violations: list[str] = []
    radius = protection_radius(tree["dap_cm"], tree["crown_radius_m"])
    if distance_m < radius:
        violations.append(f"Intervenção a {distance_m:.1f} m do tronco (raio de proteção {radius:.1f} m)")
    if not fence_ok:
        violations.append(CHECKLIST["fence_ok"] + " — NÃO")
    for key, flag in (("crown_damage", crown_damage), ("root_damage", root_damage),
                      ("soil_compaction", soil_compaction), ("material_stockpile", material_stockpile)):
        if flag:
            violations.append(CHECKLIST[key])
    return (not violations), violations


def record_inspection(rdo_id: int | None, tree_id: int, day: date, distance_m: float, fence_ok: bool,
                      crown_damage: bool, root_damage: bool, soil_compaction: bool,
                      material_stockpile: bool, notes: str = "") -> tuple[bool, list[str]]:
    tree = db.query_one("SELECT * FROM araucaria_trees WHERE id = ?", (tree_id,))
    if not tree:
        raise ValueError("Araucária não cadastrada.")
    ok, violations = evaluate_inspection(tree, distance_m, fence_ok, crown_damage, root_damage,
                                         soil_compaction, material_stockpile)
    db.execute(
        "INSERT INTO araucaria_inspections(rdo_id, tree_id, date, intervention_distance_m, fence_ok, crown_damage, "
        "root_damage, soil_compaction, material_stockpile, compliant, violations, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (rdo_id, tree_id, day.isoformat(), distance_m, int(fence_ok), int(crown_damage), int(root_damage),
         int(soil_compaction), int(material_stockpile), int(ok), "; ".join(violations), notes),
    )
    return ok, violations


def active_embargo_alerts(data_date: date | None = None, window_days: int = 60) -> list[dict]:
    data_date = data_date or date.today()
    since = (data_date - timedelta(days=window_days)).isoformat()
    return db.query(
        "SELECT i.*, t.tag FROM araucaria_inspections i JOIN araucaria_trees t ON t.id = i.tree_id "
        "WHERE i.compliant = 0 AND i.resolved = 0 AND i.date >= ? ORDER BY i.date DESC",
        (since,),
    )


def resolve_alert(inspection_id: int) -> None:
    db.execute("UPDATE araucaria_inspections SET resolved = 1 WHERE id = ?", (inspection_id,))
