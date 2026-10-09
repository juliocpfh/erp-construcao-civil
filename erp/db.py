"""Camada de persistência SQLite (dados textuais). Mídias ficam no armazenamento duplo."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from erp.config import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    email TEXT,
    organization TEXT,
    title TEXT,
    category TEXT,
    notes TEXT,
    source TEXT DEFAULT 'manual',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    full_name TEXT,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    contact_id INTEGER REFERENCES contacts(id),
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS user_permissions (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    module TEXT NOT NULL,
    PRIMARY KEY (user_id, module)
);

CREATE TABLE IF NOT EXISTS user_doc_access (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    area TEXT NOT NULL,
    PRIMARY KEY (user_id, area)
);

CREATE TABLE IF NOT EXISTS material_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    supplier_cnpj TEXT NOT NULL DEFAULT '',
    supplier_code TEXT NOT NULL DEFAULT '',
    description_norm TEXT NOT NULL,
    UNIQUE (supplier_cnpj, supplier_code, description_norm)
);

CREATE TABLE IF NOT EXISTS password_resets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,              -- 'email' (código enviado) ou 'admin' (pedido ao administrador)
    code_hash TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    closed_at TEXT,
    closed_by TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS wbs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    parent_id INTEGER REFERENCES wbs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'A Fazer',
    responsible_contact_id INTEGER REFERENCES contacts(id),
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    wbs_id INTEGER REFERENCES wbs(id),
    duration INTEGER NOT NULL,
    outdoor INTEGER NOT NULL DEFAULT 0,
    baseline_start TEXT,
    baseline_finish TEXT,
    baseline_cost REAL NOT NULL DEFAULT 0,
    progress REAL NOT NULL DEFAULT 0,
    actual_start TEXT,
    actual_finish TEXT,
    responsible_contact_id INTEGER REFERENCES contacts(id)
);

CREATE TABLE IF NOT EXISTS task_deps (
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    predecessor_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    lag INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (task_id, predecessor_id)
);

CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    unit_cost REAL NOT NULL DEFAULT 0,
    lead_time_days INTEGER NOT NULL DEFAULT 7,
    min_stock REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS task_materials (
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    quantity REAL NOT NULL,
    PRIMARY KEY (task_id, material_id)
);

CREATE TABLE IF NOT EXISTS rdo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE NOT NULL,
    weather TEXT NOT NULL,
    temperature REAL,
    rain_mm REAL DEFAULT 0,
    occurrences TEXT,
    problem_task_id INTEGER REFERENCES tasks(id),
    problem_days INTEGER DEFAULT 0,
    signed_by_contact_id INTEGER REFERENCES contacts(id),
    created_by TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS rdo_labor (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rdo_id INTEGER NOT NULL REFERENCES rdo(id) ON DELETE CASCADE,
    function TEXT NOT NULL,
    quantity INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS rdo_progress (
    rdo_id INTEGER NOT NULL REFERENCES rdo(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    progress REAL NOT NULL,
    PRIMARY KEY (rdo_id, task_id)
);

CREATE TABLE IF NOT EXISTS schedule_impacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rdo_id INTEGER REFERENCES rdo(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    days INTEGER NOT NULL,
    reason TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    quantity REAL NOT NULL,
    kind TEXT NOT NULL,
    source TEXT,
    ref_id INTEGER,
    notes TEXT,
    created_by TEXT
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT,
    supplier_name TEXT NOT NULL,
    supplier_cnpj TEXT,
    supplier_contact_id INTEGER REFERENCES contacts(id),
    issue_date TEXT NOT NULL,
    total_value REAL NOT NULL,
    kind TEXT NOT NULL DEFAULT 'Material',
    iss_value REAL DEFAULT 0,
    inss_value REAL DEFAULT 0,
    other_taxes REAL DEFAULT 0,
    tax_benefit TEXT,
    task_id INTEGER REFERENCES tasks(id),
    status TEXT NOT NULL DEFAULT 'Pendente',
    nf_media_key TEXT,
    product_media_key TEXT,
    ocr_text TEXT,
    approved_by TEXT,
    approved_at TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    material_id INTEGER NOT NULL REFERENCES materials(id),
    quantity REAL NOT NULL,
    unit_price REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier TEXT NOT NULL,
    description TEXT,
    kind TEXT NOT NULL,
    value REAL NOT NULL,
    iss_highlighted INTEGER NOT NULL DEFAULT 0,
    inss_highlighted INTEGER NOT NULL DEFAULT 0,
    iss_value REAL DEFAULT 0,
    inss_value REAL DEFAULT 0,
    status TEXT DEFAULT 'Em análise',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    category TEXT,
    filename TEXT,
    content_type TEXT,
    size_bytes INTEGER,
    local_status TEXT,
    s3_status TEXT,
    ftp_status TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    wbs_id INTEGER REFERENCES wbs(id),
    caption TEXT,
    media_key TEXT NOT NULL,
    rdo_id INTEGER REFERENCES rdo(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS araucaria_trees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT UNIQUE NOT NULL,
    dap_cm REAL NOT NULL,
    crown_radius_m REAL NOT NULL,
    location TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS araucaria_inspections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rdo_id INTEGER REFERENCES rdo(id) ON DELETE CASCADE,
    tree_id INTEGER NOT NULL REFERENCES araucaria_trees(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    intervention_distance_m REAL NOT NULL,
    fence_ok INTEGER NOT NULL DEFAULT 1,
    crown_damage INTEGER NOT NULL DEFAULT 0,
    root_damage INTEGER NOT NULL DEFAULT 0,
    soil_compaction INTEGER NOT NULL DEFAULT 0,
    material_stockpile INTEGER NOT NULL DEFAULT 0,
    compliant INTEGER NOT NULL DEFAULT 1,
    violations TEXT,
    notes TEXT,
    resolved INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS legal_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    reference TEXT,
    description TEXT,
    media_key TEXT,
    filename TEXT,
    uploaded_at TEXT
);

CREATE TABLE IF NOT EXISTS ged_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder TEXT NOT NULL,
    discipline TEXT,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    extension TEXT,
    size_bytes INTEGER,
    version INTEGER NOT NULL DEFAULT 1,
    media_key TEXT,
    uploaded_by TEXT,
    uploaded_at TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_stock_material ON stock_movements(material_id);
CREATE INDEX IF NOT EXISTS idx_invoice_status ON invoices(status);
CREATE INDEX IF NOT EXISTS idx_photos_date ON photos(date);
CREATE INDEX IF NOT EXISTS idx_impacts_task ON schedule_impacts(task_id);
"""


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or db_path()), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# colunas acrescentadas depois da 1ª versão (bancos antigos/restaurados recebem via ALTER TABLE)
MIGRATIONS = {
    "users": {"email": "TEXT", "status": "TEXT NOT NULL DEFAULT 'ativo'", "request_note": "TEXT", "last_login": "TEXT"},
    "materials": {"origin": "TEXT NOT NULL DEFAULT 'manual'", "created_at": "TEXT"},
    "invoice_items": {"description": "TEXT", "supplier_code": "TEXT"},
}


def init_db(path: str | Path | None = None) -> None:
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            existing = {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}
            for col, ddl in cols.items():
                if col not in existing:
                    conn.execute(f'ALTER TABLE "{table}" ADD COLUMN {col} {ddl}')
        conn.commit()
    finally:
        conn.close()


def query(sql: str, params: tuple | list | dict = ()) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def query_one(sql: str, params: tuple | list | dict = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def query_df(sql: str, params: tuple | list | dict = ()) -> pd.DataFrame:
    conn = connect()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def execute(sql: str, params: tuple | list | dict = ()) -> int:
    with transaction() as conn:
        cur = conn.execute(sql, params)
        return int(cur.lastrowid or 0)


def get_setting(key: str, default: str | None = None) -> str | None:
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: Any) -> None:
    execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def is_seeded() -> bool:
    try:
        row = query_one("SELECT COUNT(*) AS n FROM users")
    except sqlite3.OperationalError:
        return False
    return bool(row and row["n"])
