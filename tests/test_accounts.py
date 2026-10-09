"""Primeiro acesso, solicitação de acesso e recuperação de senha (e-mail, administrador, código de recuperação)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from erp import auth, db
from erp.services import accounts, mailer, project

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "configured", lambda settings=None: True)
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, settings=None, timeout=20: sent.append((to, subject, body)))
    return sent


@pytest.fixture
def fresh(empty_db):
    project.create_blank_project("Obra")  # senha padrão -> primeiro acesso pendente
    return empty_db


def test_first_setup_creates_admin_and_recovery_code(fresh):
    assert accounts.setup_pending()
    with pytest.raises(accounts.AccountError):
        accounts.complete_first_setup("julio", "Julio", "", "curta", "curta")
    code = accounts.complete_first_setup("Julio", "Julio C.", "julio@exemplo.com", "Obra2026x", "Obra2026x")
    assert re.fullmatch(r"[0-9A-F]{4}(-[0-9A-F]{4}){3}", code)
    assert not accounts.setup_pending()
    assert auth.authenticate("julio", "Obra2026x")["role"] == "Administrador"
    assert not auth.authenticate("admin", "admin123")
    with pytest.raises(accounts.AccountError):  # não dá para refazer
        accounts.complete_first_setup("outro", "x", "", "Obra2026x", "Obra2026x")

    # admin esqueceu a senha: código de recuperação vale uma única vez
    new_code = accounts.reset_admin_with_recovery_code("julio", code.lower(), "Nova2026x", "Nova2026x")
    assert auth.authenticate("julio", "Nova2026x") and new_code != code
    with pytest.raises(accounts.AccountError):
        accounts.reset_admin_with_recovery_code("julio", code, "Outra2026x", "Outra2026x")


def test_access_request_approval(fresh, outbox):
    accounts.complete_first_setup("admin", "Admin", "adm@ex.com", "Obra2026x", "Obra2026x")
    uid = accounts.request_access("Maria.Eng", "Maria", "maria@ex.com", "Maria2026", "Maria2026", "engenheira")
    assert not auth.authenticate("maria.eng", "Maria2026")  # aguardando liberação
    assert [r["username"] for r in accounts.pending_requests()] == ["maria.eng"]
    assert "maria.eng" not in [u["username"] for u in auth.list_users()]
    assert any("Nova solicitação" in s for _, s, _ in outbox)
    with pytest.raises(accounts.AccountError):
        accounts.request_access("maria.eng", "Outra", "o@ex.com", "Maria2026", "Maria2026")
    accounts.approve_request(uid, "Almoxarife", ["estoque"])
    user = auth.authenticate("maria.eng", "Maria2026")
    assert user["role"] == "Almoxarife" and auth.allowed_pages(user) == ["estoque"]
    assert outbox[-1][0] == "maria@ex.com"
    uid2 = accounts.request_access("intruso", "X", "x@ex.com", "Xx123456", "Xx123456")
    accounts.reject_request(uid2)
    assert not db.query_one("SELECT id FROM users WHERE id = ?", (uid2,))


def test_reset_by_email_code(fresh, outbox):
    accounts.complete_first_setup("admin", "Admin", "", "Obra2026x", "Obra2026x")
    uid = auth.create_user("joao", "Joao2026x", "Visualizador")
    accounts.update_profile(uid, "João", "joao@ex.com")
    msg = accounts.request_reset_by_email("joao@ex.com")
    assert msg == accounts.GENERIC_RESET_MSG
    assert accounts.request_reset_by_email("nao.existe") == msg  # não revela se o usuário existe
    code = re.search(r"código é: (\d{6})", outbox[-1][2]).group(1)
    with pytest.raises(accounts.AccountError):
        accounts.reset_with_code("joao", "000000" if code != "000000" else "111111", "Novo2026x", "Novo2026x")
    accounts.reset_with_code("joao", code, "Novo2026x", "Novo2026x")
    assert auth.authenticate("joao", "Novo2026x")
    with pytest.raises(accounts.AccountError):  # código usado
        accounts.reset_with_code("joao", code, "Outro2026x", "Outro2026x")


def test_email_code_locks_after_attempts(fresh, outbox):
    uid = auth.create_user("ana", "Ana2026xx", "Visualizador")
    accounts.update_profile(uid, "Ana", "ana@ex.com")
    accounts.request_reset_by_email("ana")
    code = re.search(r"(\d{6})", outbox[-1][2]).group(1)
    wrong = "123456" if code != "123456" else "654321"
    for _ in range(accounts.MAX_ATTEMPTS):
        with pytest.raises(accounts.AccountError):
            accounts.reset_with_code("ana", wrong, "Nova2026x", "Nova2026x")
    with pytest.raises(accounts.AccountError, match="expirado"):
        accounts.reset_with_code("ana", code, "Nova2026x", "Nova2026x")


def test_reset_by_admin(fresh):
    uid = auth.create_user("pedro", "Pedro2026", "Visualizador")
    accounts.request_reset_by_admin("pedro")
    accounts.request_reset_by_admin("pedro")  # não duplica
    reqs = accounts.open_admin_reset_requests()
    assert len(reqs) == 1 and accounts.pending_count() == 1
    temp = accounts.resolve_admin_reset(reqs[0]["id"], "admin")
    user = auth.authenticate("pedro", temp)
    assert user["id"] == uid and user["must_change_password"]
    assert accounts.pending_count() == 0


def test_email_unavailable_without_smtp(fresh):
    with pytest.raises(accounts.AccountError, match="não está configurado"):
        accounts.request_reset_by_email("admin")


def test_first_access_screen_in_app(fresh):
    import streamlit as st

    st.cache_resource.clear()
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("criar o administrador" in t.value for t in at.title)
    at.text_input[0].input("Julio")
    at.text_input[1].input("julio")
    at.text_input[3].input("Obra2026x")
    at.text_input[4].input("Obra2026x")
    at.button[0].click().run()
    assert not at.exception
    assert any("código de recuperação" in t.value for t in at.title)
    assert at.code[0].value.count("-") == 3


def test_login_screen_has_forgot_and_signup(empty_db):
    import streamlit as st

    project.create_blank_project("Obra", admin_password="Senha1234", must_change_password=False)
    st.cache_resource.clear()
    at = AppTest.from_file(APP, default_timeout=60).run()
    labels = [b.label for b in at.button]
    assert "🔑 Esqueci minha senha" in labels and "📝 Solicitar acesso" in labels
    next(b for b in at.button if b.label == "📝 Solicitar acesso").click().run()
    assert not at.exception
    assert any("Solicitar acesso" in h.value for h in at.subheader)
    next(b for b in at.button if b.label == "← Voltar ao login").click().run()
    next(b for b in at.button if b.label == "🔑 Esqueci minha senha").click().run()
    assert not at.exception
    assert any("Esqueci minha senha" in h.value for h in at.subheader)


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3

    old = tmp_path / "antigo.db"
    conn = sqlite3.connect(old)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, full_name TEXT, "
                 "password_hash TEXT NOT NULL, role TEXT NOT NULL, must_change_password INTEGER NOT NULL DEFAULT 0, "
                 "active INTEGER NOT NULL DEFAULT 1, contact_id INTEGER, created_at TEXT)")
    conn.execute("INSERT INTO users(username, password_hash, role) VALUES ('velho', 'x', 'Administrador')")
    conn.commit()
    conn.close()
    db.init_db(old)
    conn = sqlite3.connect(old)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    status = conn.execute("SELECT status FROM users").fetchone()[0]
    conn.close()
    assert {"email", "status", "request_note", "last_login"} <= cols and status == "ativo"
