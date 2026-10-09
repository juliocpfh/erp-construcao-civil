"""Backup do banco num servidor FTP real (pyftpdlib local): teste de acesso, envio conferido, versões e restauração."""
from __future__ import annotations

import threading
import time
from datetime import date

import pytest

pytest.importorskip("pyftpdlib")
from pyftpdlib.authorizers import DummyAuthorizer  # noqa: E402
from pyftpdlib.handlers import FTPHandler  # noqa: E402
from pyftpdlib.servers import FTPServer  # noqa: E402

from erp import db  # noqa: E402
from erp.services import backup, project  # noqa: E402
from erp.storage import DualStorage, FTPBackend  # noqa: E402


@pytest.fixture
def ftp_server(tmp_path):
    root = tmp_path / "ftp_root"
    root.mkdir()
    auth = DummyAuthorizer()
    auth.add_user("obra", "s3nh@ftp", str(root), perm="elradfmwMT")
    auth.add_user("leitor", "leitor123", str(root), perm="elr")
    handler = type("H", (FTPHandler,), {"authorizer": auth, "passive_ports": range(60000, 60100)})
    server = FTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=server.serve_forever, kwargs={"timeout": 0.2}, daemon=True)
    t.start()
    yield {"FTP_HOST": "127.0.0.1", "FTP_PORT": str(server.address[1]), "FTP_USER": "obra",
           "FTP_PASSWORD": "s3nh@ftp", "FTP_BASE_DIR": "/backup_obra", "FTP_TLS": "0"}, root
    server.close_all()


@pytest.fixture(autouse=True)
def reset_backup_state():
    backup._state.update(last_check=0.0, last_hash=None, last_ok=None, last_error=None, armed=False, startup=None,
                         problem=None, pulled=None)


def test_ftp_access_check(empty_db, ftp_server):
    settings, _ = ftp_server
    ok, msg = FTPBackend(settings).test_write()
    assert ok, msg
    assert "Gravação e leitura confirmadas" in msg
    ok, msg = FTPBackend({**settings, "FTP_USER": "leitor", "FTP_PASSWORD": "leitor123"}).test_write()
    assert not ok and "permissão de gravação" in msg
    ok, msg = FTPBackend({**settings, "FTP_PASSWORD": "errada"}).test_write()
    assert not ok
    ok, _ = FTPBackend({**settings, "FTP_PORT": "1"}).test_write()  # endereço antigo/inacessível
    assert not ok


def test_database_lives_on_ftp(empty_db, ftp_server):
    settings, root = ftp_server
    storage = DualStorage(settings=settings)
    project.create_blank_project("Obra FTP", "Curitiba/PR", date(2026, 10, 1), admin_password="Senha1234")
    res = backup.push_remote(storage=storage)
    assert res["ok"], res
    assert (root / "backup_obra" / "backup-banco" / "erp_obra_latest.db").exists()
    assert (root / "backup_obra" / "backup-banco" / "latest.json").exists()

    time.sleep(1.1)
    db.set_setting("project_location", "Araucária/PR")
    assert backup.push_remote(storage=storage)["ok"]
    assert len(backup.list_versions(storage)) == 2

    project.wipe_all()
    assert backup.restore_latest_remote(storage)
    assert project.project_info()["location"] == "Araucária/PR"

    old = backup.list_versions(storage)[-1]
    backup.restore_from_remote(old, storage=storage)
    assert project.project_info()["location"] == "Curitiba/PR"
    assert backup.last_restore()["version"] == old.rsplit("/", 1)[-1]


def test_unreachable_ftp_on_startup_is_reported(empty_db, ftp_server):
    settings, _ = ftp_server
    storage = DualStorage(settings={**settings, "FTP_PORT": "1"})
    assert not backup.restore_latest_remote(storage)
    st = backup.status()["startup"]
    assert st["configured"] and not st["ok"] and not st["reachable"]
    assert "inacessível" in st["message"]
    assert not backup.status()["armed"]


def test_connection_loss_alert_lifecycle(empty_db, ftp_server):
    from erp.ui.common import ftp_steps

    settings, _ = ftp_server
    good = DualStorage(settings=settings)
    project.create_blank_project("Obra", admin_password="Senha1234")
    assert backup.push_remote(storage=good)["ok"]
    assert backup.connection_problem() is None

    # FTP mudou de endereço durante o uso: envio falha -> alerta "unreachable"
    db.set_setting("project_location", "x")
    res = backup.push_remote(storage=DualStorage(settings={**settings, "FTP_PORT": "1"}))
    assert not res["ok"]
    problem = backup.connection_problem()
    assert problem["kind"] == "unreachable" and not problem["startup"]
    steps = " ".join(ftp_steps(problem))
    assert "Testar acesso" in steps and "Secrets" in steps and "Enviar backup agora" in steps

    # senha trocada -> alerta "auth"
    assert not backup.health_check(DualStorage(settings={**settings, "FTP_PASSWORD": "velha"}))
    assert backup.connection_problem()["kind"] == "auth"

    # corrigido: verificação limpa o alerta
    assert backup.health_check(good)
    assert backup.connection_problem() is None


def test_startup_alert_requires_restore(empty_db, ftp_server):
    from erp.ui.common import ftp_steps

    settings, _ = ftp_server
    good = DualStorage(settings=settings)
    project.create_blank_project("Obra real", admin_password="Senha1234")
    assert backup.push_remote(storage=good)["ok"]
    project.wipe_all()
    backup._state.update(armed=False, problem=None)

    assert not backup.restore_latest_remote(DualStorage(settings={**settings, "FTP_PORT": "1"}))
    problem = backup.connection_problem()
    assert problem["startup"] and problem["kind"] == "unreachable"
    assert "Restaurar a última versão do servidor" in " ".join(ftp_steps(problem))

    assert backup.health_check(good)  # conexão volta, mas o banco ainda não foi restaurado
    assert backup.connection_problem()["startup"]
    backup.restore_from_remote(storage=good)
    assert backup.connection_problem() is None
    assert project.project_info()["name"] == "Obra real"


def test_alert_shown_on_every_page(empty_db):
    from streamlit.testing.v1 import AppTest

    project.create_blank_project("Obra", admin_password="Senha1234", must_change_password=False)
    script = ("from datetime import datetime\nfrom erp.services import backup\nfrom erp.ui.common import ftp_problem_alert\n"
              "ftp_problem_alert({'kind': 'unreachable', 'detail': 'timed out', 'since': datetime.now(), "
              "'startup': False}, admin={admin})\n")
    at = AppTest.from_string(script.replace("{admin}", "True"), default_timeout=30).run()
    assert not at.exception
    assert any("SEM CONEXÃO COM O FTP" in m.value for m in at.markdown)
    assert any("Testar acesso" in m.value for m in at.markdown)
    at = AppTest.from_string(script.replace("{admin}", "False"), default_timeout=30).run()
    assert any("Avise o administrador" in m.value for m in at.markdown)
    assert not any("Testar acesso" in m.value for m in at.markdown)


def _use(root, monkeypatch):
    """Alterna para a pasta de dados de outra instalação (outro computador ou o site)."""
    monkeypatch.setenv("ERP_DATA_DIR", str(root))
    backup._state.update(last_hash=None, armed=False, problem=None)


def test_two_installations_share_the_ftp_database(empty_db, ftp_server, tmp_path, monkeypatch):
    settings, _ = ftp_server
    storage = DualStorage(settings=settings)
    pc, site = tmp_path / "pc", tmp_path / "site"

    _use(pc, monkeypatch)
    project.create_blank_project("Obra compartilhada", admin_password="Senha1234")
    assert backup.sync(storage) == "pushed"

    _use(site, monkeypatch)  # site abre vazio e baixa do FTP
    db.init_db()
    assert backup.restore_latest_remote(storage)
    db.set_setting("project_location", "lançado no site")
    assert backup.sync(storage) == "pushed"

    _use(pc, monkeypatch)  # PC sem alterações locais: baixa a versão do site
    assert backup.sync(storage) == "pulled"
    assert project.project_info()["location"] == "lançado no site"
    assert backup.sync(storage) == "unchanged"

    # lançamentos simultâneos nos dois lugares -> conflito, nada é sobrescrito
    db.set_setting("project_description", "lançado no PC")
    _use(site, monkeypatch)
    db.set_setting("project_description", "lançado no site de novo")
    assert backup.sync(storage) == "pushed"
    _use(pc, monkeypatch)
    assert backup.sync(storage) == "conflict"
    assert backup.connection_problem()["kind"] == "blocked"
    assert backup.remote_manifest(storage)["project"] == "Obra compartilhada"
    assert project.project_info()["description"] == "lançado no PC"


def test_local_mode_never_touches_ftp(empty_db, ftp_server):
    from erp import storage_mode
    from erp.storage import store_media

    settings, root = ftp_server
    storage_mode.set_mode(storage_mode.LOCAL)
    project.create_blank_project("Obra local", admin_password="Senha1234")
    s = DualStorage(settings=settings)
    assert not s.remote
    assert backup.sync(s) == "unchanged"
    assert not backup.push_remote(storage=s)["ok"]
    r = store_media(b"foto", "f.jpg", "fotos-obra", storage=s)
    assert r.ftp == "não configurado"
    assert not any(root.rglob("*.*"))
