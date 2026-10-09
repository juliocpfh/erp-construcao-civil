"""Inicializador do instalador Windows: pasta de dados, OCR embutido e modo de acesso."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("erp_launcher", ROOT / "installer" / "erp_launcher.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_launcher_env_and_mode(tmp_path, monkeypatch):
    launcher = _load()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    data = launcher.data_dir()
    assert data == tmp_path / "ERP Obras" / "data" and data.exists()
    assert launcher.storage_mode(data) is None
    (data / "storage_mode.json").write_text(json.dumps({"mode": "ftp"}))
    assert launcher.storage_mode(data) == "ftp"
    env = launcher.build_env(data)
    assert env["ERP_DATA_DIR"] == str(data) and env["ERP_ENV_PATH"] == str(data / ".env")


def test_installer_files_consistent():
    iss = (ROOT / "installer" / "erp_obras.iss").read_text(encoding="utf-8")
    ps1 = (ROOT / "installer" / "build_windows.ps1").read_text(encoding="utf-8")
    assert "erp_launcher.py" in iss and "erp_launcher.py" in ps1
    assert "por.traineddata" in ps1 and "PrivilegesRequired=lowest" in iss
