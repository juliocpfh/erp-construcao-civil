#!/usr/bin/env bash
# Linux/macOS: prepara o ambiente na primeira vez e inicia o ERP (acessível na rede local).
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Primeira execução: preparando o ambiente..."
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi
echo "ERP Obras: http://localhost:8501  (celular na mesma rede: http://<IP-deste-computador>:8501)"
echo "Banco de dados: $(pwd)/data/erp_obra.db"
exec .venv/bin/python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --browser.gatherUsageStats false
