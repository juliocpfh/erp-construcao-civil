"""Inicializador do ERP Obras instalado no Windows (atalho da área de trabalho).

- Dados ficam em %LOCALAPPDATA%\\ERP Obras\\data (fora da pasta do programa: sobrevivem a atualizações).
- Usa o Tesseract (OCR de NF) e o ffmpeg embutidos no instalador.
- Modo "disco local": só este computador acessa (127.0.0.1). Modo FTP: libera a rede local (celular no Wi-Fi).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
PORT = 8501


def data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    path = base / "ERP Obras" / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def storage_mode(data: Path) -> str | None:
    try:
        return json.loads((data / "storage_mode.json").read_text(encoding="utf-8")).get("mode")
    except (OSError, ValueError):
        return None


def running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as r:
            return r.status == 200
    except OSError:
        return False


def lan_ips() -> list[str]:
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


def build_env(data: Path) -> dict:
    env = dict(os.environ)
    env["ERP_DATA_DIR"] = str(data)
    env["ERP_ENV_PATH"] = str(data / ".env")
    tess = APP_DIR / "tesseract" / "tesseract.exe"
    if tess.exists():
        env["ERP_TESSERACT_CMD"] = str(tess)
        env["TESSDATA_PREFIX"] = str(tess.parent / "tessdata")
    extra = [str(p) for p in (APP_DIR / "ffmpeg", APP_DIR / "tesseract") if p.exists()]
    env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


def main() -> int:
    data = data_dir()
    url = f"http://localhost:{PORT}"
    if running(PORT):  # já aberto: só abre o navegador
        webbrowser.open(url)
        return 0
    mode = storage_mode(data)
    address = "0.0.0.0" if mode == "ftp" else "127.0.0.1"
    cmd = [sys.executable, "-m", "streamlit", "run", str(APP_DIR / "app.py"), "--server.address", address,
           "--server.port", str(PORT), "--server.headless", "true", "--browser.gatherUsageStats", "false",
           "--global.developmentMode", "false"]
    proc = subprocess.Popen(cmd, cwd=str(APP_DIR), env=build_env(data))
    for _ in range(120):
        if running(PORT) or proc.poll() is not None:
            break
        time.sleep(0.5)
    print("=" * 66)
    print(" ERP Obras em execução")
    print(f" Neste computador: {url}")
    if mode == "ftp":
        for ip in lan_ips():
            print(f" Celular no mesmo Wi-Fi: http://{ip}:{PORT}")
    else:
        print(" Modo disco local: acessível somente neste computador.")
    print(f" Dados: {data}")
    print(" Para encerrar o sistema, feche esta janela.")
    print("=" * 66)
    webbrowser.open(url)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0


if __name__ == "__main__":
    sys.exit(main())
