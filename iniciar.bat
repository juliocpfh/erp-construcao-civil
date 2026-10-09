@echo off
chcp 65001 >nul
title ERP Obras
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale o Python 3.12 em https://www.python.org/downloads/
  echo e marque a opcao "Add Python to PATH" na instalacao.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Primeira execucao: preparando o ambiente (alguns minutos^)...
  python -m venv .venv || (pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (pause & exit /b 1)
)

echo.
echo ================================================================
echo  ERP Obras rodando. Neste computador: http://localhost:8501
echo  No celular (mesmo Wi-Fi), use um destes enderecos:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo     http://%%a:8501
echo  Banco de dados: %~dp0data\erp_obra.db
echo  Para encerrar, feche esta janela.
echo ================================================================
echo.
".venv\Scripts\python.exe" -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --browser.gatherUsageStats false
pause
