"""EAP/WBS: árvore, numeração, visualizações (Graphviz, tabela recuada, Kanban) e status."""
from __future__ import annotations

import textwrap

import graphviz
import pandas as pd

from erp import db
from erp.config import WBS_STATUS

STATUS_COLORS = {"A Fazer": "#D6DBDF", "Em Andamento": "#F9E79F", "Concluído": "#ABEBC6"}


def load_wbs() -> pd.DataFrame:
    df = db.query_df(
        "SELECT w.*, c.name AS responsible, "
        "(SELECT COALESCE(SUM(t.baseline_cost), 0) FROM tasks t WHERE t.wbs_id = w.id) AS direct_cost, "
        "(SELECT AVG(t.progress) FROM tasks t WHERE t.wbs_id = w.id) AS direct_progress "
        "FROM wbs w LEFT JOIN contacts c ON c.id = w.responsible_contact_id"
    )
    if df.empty:
        return df
    df["sort_key"] = df["code"].map(lambda c: tuple(int(x) for x in c.split(".")))
    df = df.sort_values("sort_key").reset_index(drop=True)
    df["level"] = df["code"].str.count(r"\.")
    # roll-up de custo e avanço (ponderado pelo custo) para os níveis superiores
    costs, earned = {}, {}
    for row in df.sort_values("level", ascending=False).itertuples():
        own_cost = float(row.direct_cost) if pd.notna(row.direct_cost) else 0.0
        own_prog = float(row.direct_progress) if pd.notna(row.direct_progress) else 0.0
        own_earned = own_cost * own_prog / 100.0
        child_cost = sum(costs[c] for c in df[df["parent_id"] == row.id]["id"])
        child_earned = sum(earned[c] for c in df[df["parent_id"] == row.id]["id"])
        costs[row.id] = own_cost + child_cost
        earned[row.id] = own_earned + child_earned
    df["budget"] = df["id"].map(costs)
    df["progress"] = df["id"].map(lambda i: 100 * earned[i] / costs[i] if costs[i] else 0.0)
    return df


def next_child_code(parent_code: str | None) -> str:
    rows = db.query("SELECT code FROM wbs")
    codes = {r["code"] for r in rows}
    if not parent_code:
        n = 1
        while str(n) in codes:
            n += 1
        return str(n)
    n = 1
    while f"{parent_code}.{n}" in codes:
        n += 1
    return f"{parent_code}.{n}"


def add_deliverable(parent_id: int | None, name: str, description: str = "", responsible_contact_id: int | None = None,
                    status: str = "A Fazer") -> int:
    parent = db.query_one("SELECT code FROM wbs WHERE id = ?", (parent_id,)) if parent_id else None
    code = next_child_code(parent["code"] if parent else None)
    return db.execute(
        "INSERT INTO wbs(code, parent_id, name, description, status, responsible_contact_id, sort_order) "
        "VALUES (?,?,?,?,?,?, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM wbs))",
        (code, parent_id, name, description, status, responsible_contact_id),
    )


def set_status(wbs_id: int, status: str) -> None:
    if status not in WBS_STATUS:
        raise ValueError(status)
    db.execute("UPDATE wbs SET status = ? WHERE id = ?", (status, wbs_id))


def sync_status_from_tasks() -> None:
    df = load_wbs()
    with db.transaction() as conn:
        for row in df.itertuples():
            p = float(row.progress or 0)
            status = "Concluído" if p >= 99.9 else ("Em Andamento" if p > 0 else "A Fazer")
            conn.execute("UPDATE wbs SET status = ? WHERE id = ?", (status, int(row.id)))


def graphviz_tree(df: pd.DataFrame, max_level: int = 3, horizontal: bool = False) -> graphviz.Digraph:
    g = graphviz.Digraph("EAP")
    g.attr(rankdir="LR" if horizontal else "TB", splines="ortho", nodesep="0.25", ranksep="0.45")
    g.attr("node", shape="box", style="rounded,filled", fontname="Helvetica", fontsize="12", margin="0.15,0.06")
    visible = df[df["level"] <= max_level]
    ids = set(visible["id"])
    for row in visible.itertuples():
        color = STATUS_COLORS.get(row.status, "#FFFFFF")
        border = "#1F4E79" if row.level == 0 else "#566573"
        name = "\n".join(textwrap.wrap(row.name, 22))
        label = f"{row.code}\n{name}\n{row.progress:.0f}%"
        g.node(str(row.id), label=label, fillcolor=color, color=border, penwidth="2" if row.level == 0 else "1")
    for row in visible.itertuples():
        if pd.notna(row.parent_id) and int(row.parent_id) in ids:
            g.edge(str(int(row.parent_id)), str(row.id), arrowhead="none")
    return g


def indented_table(df: pd.DataFrame) -> pd.DataFrame:
    """Tabela estruturada recuada (estilo MindView)."""
    def indent(row):
        prefix = "  " * row["level"] + ("└─ " if row["level"] else "■ ")
        return f"{prefix}{row['code']}  {row['name']}"

    out = pd.DataFrame({
        "EAP": df.apply(indent, axis=1),
        "Nível": df["level"],
        "Status": df["status"],
        "Responsável": df["responsible"].fillna("-"),
        "Orçamento (R$)": df["budget"].round(2),
        "Avanço": df["progress"].round(1),
    })
    return out
