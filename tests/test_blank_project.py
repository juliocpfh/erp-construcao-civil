"""Projeto novo em branco: telas sem dados, reset, backup/restauração e login sem senhas expostas."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from erp import auth, db
from erp.services import backup, project

APP = str(Path(__file__).resolve().parent.parent / "app.py")
PAGES = ["page_dashboard", "page_wbs", "page_schedule", "page_rdo", "page_fiscal", "page_inventory", "page_media",
         "page_environment", "page_ged", "page_contacts", "page_admin", "page_connections", "page_project"]


@pytest.fixture
def blank(empty_db):
    project.create_blank_project("Edifício Teste", "Curitiba/PR", date(2026, 10, 1), admin_password="Senha1234",
                                 must_change_password=False)
    return empty_db


def _page(module: str) -> AppTest:
    at = AppTest.from_string(f"from erp.ui import {module}\nfrom erp.ui.common import inject_css\ninject_css()\n{module}.render()\n",
                             default_timeout=60)
    at.session_state["user"] = auth.authenticate("admin", "Senha1234")
    return at.run()


def test_first_run_is_blank_and_hides_credentials(empty_db, monkeypatch):
    import streamlit as st

    monkeypatch.delenv("ERP_DEMO", raising=False)
    st.cache_resource.clear()  # bootstrap() é cacheado por processo
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "admin123" not in text and "campo123" not in text
    assert db.query_one("SELECT COUNT(*) AS n FROM tasks")["n"] == 0
    assert [u["username"] for u in auth.list_users()] == ["admin"]
    assert auth.authenticate("admin", "admin123")["must_change_password"]


@pytest.mark.parametrize("module", PAGES)
def test_every_page_renders_on_blank_project(blank, module):
    at = _page(module)
    assert not at.exception, at.exception


def test_create_blank_project_wipes_everything(seeded):
    assert db.query_one("SELECT COUNT(*) AS n FROM tasks")["n"] > 0
    project.create_blank_project("Obra Nova", "Araucária/PR", date(2026, 11, 1), admin_password="Nova12345")
    assert db.query_one("SELECT COUNT(*) AS n FROM wbs")["n"] == 1  # raiz = obra
    for table in ("tasks", "invoices", "rdo", "materials", "contacts", "media", "photos"):
        assert db.query_one(f"SELECT COUNT(*) AS n FROM {table}")["n"] == 0, table
    info = project.project_info()
    assert info["name"] == "Obra Nova" and info["location"] == "Araucária/PR" and info["start"] == "2026-11-01"
    assert auth.authenticate("admin", "Nova12345") and not auth.authenticate("almoxarife", "campo123")


def test_backup_roundtrip(blank):  # arquivo baixado/enviado pelo navegador
    db.set_setting("project_name", "Antes do backup")
    data = backup.snapshot()
    assert backup.validate(data) is None
    db.set_setting("project_name", "Depois")
    backup.restore(data)
    assert project.project_info()["name"] == "Antes do backup"


def test_restore_rejects_invalid_file(blank):
    with pytest.raises(ValueError):
        backup.restore(b"isto nao e um banco")
    assert project.project_info()["name"] == "Edifício Teste"


class _MemBackend:
    def __init__(self, store):
        self.store, self.configured = store, True

    def upload(self, key, data, content_type=None):
        self.store[key] = data

    def download(self, key):
        return self.store[key]

    def list_files(self, prefix):
        return sorted(k for k in self.store if k.startswith(prefix))

    def test(self):
        return True, "ok"


@pytest.fixture(autouse=True)
def reset_backup_state():
    backup._state.update(last_check=0.0, last_hash=None, last_ok=None, last_error=None, armed=False, startup=None)


@pytest.fixture
def mem_storage(tmp_path):
    from erp.storage import DualStorage

    store: dict[str, bytes] = {}
    storage = DualStorage(settings={}, local_root=tmp_path / "m")
    storage.s3 = _MemBackend(store)
    return storage, store


def test_remote_backup_verified_and_auto_restore(blank, mem_storage):
    storage, store = mem_storage
    db.set_setting("project_name", "Na nuvem")
    res = backup.push_remote(storage=storage)
    assert res["ok"], res
    assert {backup.LATEST_KEY, backup.MANIFEST_KEY, res["manifest"]["key"]} <= set(store)
    assert backup.remote_manifest(storage)["project"] == "Na nuvem"
    assert backup.status()["last_push"]["version"] == res["manifest"]["version"]

    project.wipe_all()  # simula reinício do Streamlit Cloud com disco apagado
    assert backup.restore_latest_remote(storage=storage)
    assert project.project_info()["name"] == "Na nuvem"
    assert backup.last_restore()["version"] == res["manifest"]["version"]
    assert backup.status()["startup"]["ok"]


def test_blank_db_never_overwrites_remote_backup(blank, mem_storage):
    storage, store = mem_storage
    db.set_setting("project_name", "Obra real")
    assert backup.push_remote(storage=storage)["ok"]
    good = store[backup.LATEST_KEY]

    # reinício em que o FTP estava inacessível: banco em branco, envio não armado
    project.create_blank_project("Nova Obra", admin_password="Senha1234")
    backup.arm(False)
    blocked = backup.push_remote(storage=storage)
    assert not blocked["ok"] and blocked["blocked"]
    assert store[backup.LATEST_KEY] == good

    # admin corrige o FTP e restaura: envio volta a funcionar
    backup.restore_from_remote(storage=storage)
    assert project.project_info()["name"] == "Obra real"
    db.set_setting("project_location", "Curitiba")
    assert backup.push_remote(storage=storage)["ok"]


def test_restore_older_version(blank, mem_storage):
    import time

    storage, _ = mem_storage
    db.set_setting("project_name", "v1")
    v1 = backup.push_remote(storage=storage)["manifest"]["key"]
    time.sleep(1.1)
    db.set_setting("project_name", "v2")
    backup.push_remote(storage=storage)
    versions = backup.list_versions(storage)
    assert len(versions) == 2 and versions[-1] == v1
    backup.restore_from_remote(v1, storage=storage)
    assert project.project_info()["name"] == "v1"
    assert not backup.status()["armed"]  # versão antiga: não sobrescreve automaticamente
