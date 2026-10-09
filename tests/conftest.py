"""Fixtures: cada teste roda com banco/mídias/.env isolados em diretório temporário."""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

TODAY = date(2026, 10, 9)
MASTER_KEY = Fernet.generate_key().decode()


def _point_env(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setenv("ERP_DATA_DIR", str(root))
    monkeypatch.setenv("ERP_ENV_PATH", str(root / ".env"))
    monkeypatch.setenv("ERP_MASTER_KEY", MASTER_KEY)
    monkeypatch.delenv("ERP_DB_PATH", raising=False)
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "S3_BUCKET", "FTP_HOST", "FTP_USER", "FTP_PASSWORD"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Nunca toca no banco/.env reais do projeto."""
    _point_env(monkeypatch, tmp_path / "isolated")


@pytest.fixture
def empty_db(tmp_path, monkeypatch):
    from erp import db

    _point_env(monkeypatch, tmp_path)
    db.init_db()
    return tmp_path


@pytest.fixture(scope="session")
def seeded_template(tmp_path_factory):
    root = tmp_path_factory.mktemp("seed_template")
    mp = pytest.MonkeyPatch()
    _point_env(mp, root)
    from erp.seed import seed_database

    summary = seed_database(today=TODAY, with_media=True)
    mp.undo()
    return root, summary


@pytest.fixture
def seeded(seeded_template, tmp_path, monkeypatch):
    template, summary = seeded_template
    target = tmp_path / "data"
    shutil.copytree(template, target)
    _point_env(monkeypatch, target)
    return summary
