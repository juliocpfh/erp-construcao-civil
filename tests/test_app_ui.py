"""Testes de interface com o AppTest do Streamlit (renderização headless de cada módulo)."""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from erp import auth

APP = str(Path(__file__).resolve().parent.parent / "app.py")
PAGES = ["page_dashboard", "page_wbs", "page_schedule", "page_rdo", "page_fiscal", "page_inventory", "page_media",
         "page_environment", "page_ged", "page_contacts", "page_admin", "page_connections", "page_project"]


def _page(module: str, username: str) -> AppTest:
    at = AppTest.from_string(f"from erp.ui import {module}\nfrom erp.ui.common import inject_css\ninject_css()\n{module}.render()\n",
                             default_timeout=120)
    user = auth.authenticate(username, {"admin": "admin123", "almoxarife": "campo123", "visualizador": "visual123"}[username])
    at.session_state["user"] = user
    return at.run()


def test_login_screen_and_admin_login(seeded):
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    assert any("ERP de Gestão de Obras" in t.value for t in at.title)
    at.sidebar.text_input[0].input("admin")
    at.sidebar.text_input[1].input("admin123")
    at.sidebar.button[0].click().run()
    assert not at.exception
    assert at.session_state["user"]["role"] == "Administrador"


def test_wrong_password(seeded):
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.sidebar.text_input[0].input("admin")
    at.sidebar.text_input[1].input("errada")
    at.sidebar.button[0].click().run()
    assert "user" not in at.session_state
    assert at.sidebar.error


def test_forced_password_change_screen(seeded):
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.sidebar.text_input[0].input("fiscal.banco")
    at.sidebar.text_input[1].input("Prov@2026")
    at.sidebar.button[0].click().run()
    assert any("Troca de senha" in t.value for t in at.title)


@pytest.mark.parametrize("module", PAGES)
def test_every_page_renders_for_admin(seeded, module):
    at = _page(module, "admin")
    assert not at.exception, at.exception


@pytest.mark.parametrize("module", ["page_dashboard", "page_fiscal", "page_rdo", "page_schedule"])
def test_viewer_pages_are_read_only(seeded, module):
    at = _page(module, "visualizador")
    assert not at.exception, at.exception


@pytest.mark.parametrize("module", ["page_admin", "page_connections", "page_project"])
def test_admin_pages_blocked_for_non_admin(seeded, module):
    at = _page(module, "almoxarife")
    assert any("restrito" in e.value for e in at.error)


def test_almoxarife_inventory_page(seeded):
    at = _page("page_inventory", "almoxarife")
    assert not at.exception
    assert any("RUPTURA" in m.value for m in at.markdown)  # alerta piscante de lead time


def test_ged_shows_only_allowed_folders(seeded):
    uid = auth.authenticate("visualizador", "visual123")["id"]
    auth.set_permissions(uid, ["ged", "ambiental"])
    auth.set_doc_areas(uid, ["ged:Projetos", "legal:ABNT"])
    at = _page("page_ged", "visualizador")
    assert not at.exception
    labels = [t.label for t in at.tabs]
    assert labels == ["📁 Projetos"]
    at = _page("page_environment", "visualizador")
    assert not at.exception
    assert any("ABNT" in c.value for c in at.caption)
