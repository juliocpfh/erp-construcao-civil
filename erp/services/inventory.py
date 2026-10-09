"""Almoxarifado: NF aprovada dá entrada, RDO/consumo diário dá baixa, alerta de Lead Time."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from erp import db
from erp.services.scheduling import compute_schedule


def stock_levels() -> pd.DataFrame:
    return db.query_df(
        "SELECT m.id, m.code, m.name, m.unit, m.unit_cost, m.lead_time_days, m.min_stock, "
        "COALESCE(SUM(s.quantity), 0) AS stock "
        "FROM materials m LEFT JOIN stock_movements s ON s.material_id = m.id "
        "GROUP BY m.id ORDER BY m.name"
    )


def material_stock(material_id: int) -> float:
    row = db.query_one("SELECT COALESCE(SUM(quantity), 0) AS q FROM stock_movements WHERE material_id = ?",
                       (material_id,))
    return float(row["q"]) if row else 0.0


def add_movement(material_id: int, quantity: float, day: date, kind: str, source: str,
                 ref_id: int | None = None, notes: str = "", user: str = "", conn=None) -> None:
    sql = ("INSERT INTO stock_movements(material_id, date, quantity, kind, source, ref_id, notes, created_by) "
           "VALUES (?,?,?,?,?,?,?,?)")
    params = (material_id, day.isoformat(), quantity, kind, source, ref_id, notes, user)
    if conn is not None:
        conn.execute(sql, params)
    else:
        db.execute(sql, params)


def register_consumption(material_id: int, quantity: float, day: date, rdo_id: int | None = None,
                         notes: str = "", user: str = "", allow_negative: bool = False) -> None:
    if quantity <= 0:
        raise ValueError("Quantidade consumida deve ser positiva.")
    if not allow_negative and material_stock(material_id) < quantity:
        raise ValueError("Consumo maior que o saldo em estoque.")
    add_movement(material_id, -abs(quantity), day, "SAIDA", "RDO" if rdo_id else "Consumo diário",
                 rdo_id, notes, user)


def approve_invoice(invoice_id: int, user: str) -> dict:
    """Aprova a NF: soma ao Custo Real (CR) e dá entrada dos itens no estoque."""
    inv = db.query_one("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
    if not inv:
        raise ValueError("NF não encontrada.")
    if inv["status"] == "Aprovada":
        return inv
    items = db.query("SELECT * FROM invoice_items WHERE invoice_id = ?", (invoice_id,))
    with db.transaction() as conn:
        conn.execute("UPDATE invoices SET status = 'Aprovada', approved_by = ?, approved_at = ? WHERE id = ?",
                     (user, db.now_iso(), invoice_id))
        for it in items:
            add_movement(it["material_id"], it["quantity"], date.fromisoformat(inv["issue_date"]), "ENTRADA",
                         "NF", invoice_id, f"NF {inv['number']} - {inv['supplier_name']}", user, conn=conn)
    return db.query_one("SELECT * FROM invoices WHERE id = ?", (invoice_id,))


def reject_invoice(invoice_id: int, user: str) -> None:
    db.execute("UPDATE invoices SET status = 'Rejeitada', approved_by = ?, approved_at = ? WHERE id = ?",
               (user, db.now_iso(), invoice_id))


def lead_time_alerts(data_date: date | None = None, sched: pd.DataFrame | None = None,
                     critical_only: bool = True) -> pd.DataFrame:
    """Materiais cujo saldo não cobre a demanda das próximas tarefas críticas dentro do Lead Time.

    Para cada material: janela = hoje + lead time + 7 dias de segurança. Demanda = quantidade
    restante (1 - % executado) das tarefas (críticas) que estarão em execução nessa janela.
    """
    data_date = data_date or date.today()
    sched = sched if sched is not None else compute_schedule(data_date)
    levels = stock_levels().set_index("id")
    needs = db.query_df("SELECT task_id, material_id, quantity FROM task_materials")
    if needs.empty or sched.empty:
        return pd.DataFrame()
    df = needs.merge(sched[["id", "code", "name", "start", "finish", "progress", "critical"]],
                     left_on="task_id", right_on="id")
    if critical_only:
        df = df[df["critical"]]
    df = df[df["progress"] < 100]
    rows = []
    for mat_id, grp in df.groupby("material_id"):
        mat = levels.loc[mat_id]
        horizon = data_date + timedelta(days=int(mat["lead_time_days"]) + 7)
        upcoming = grp[(grp["start"] <= horizon) & (grp["finish"] >= data_date)]
        if upcoming.empty:
            continue
        required = float((upcoming["quantity"] * (1 - upcoming["progress"] / 100.0)).sum())
        stock = float(mat["stock"])
        if stock < required:
            rows.append({
                "material_id": int(mat_id), "material": mat["name"], "unit": mat["unit"],
                "stock": stock, "required": required, "shortfall": required - stock,
                "lead_time_days": int(mat["lead_time_days"]),
                "order_by": data_date,  # já deveria ter sido pedido: pedir hoje
                "tasks": ", ".join(upcoming["code"].tolist()),
                "first_need": min(upcoming["start"]),
            })
    return pd.DataFrame(rows)
