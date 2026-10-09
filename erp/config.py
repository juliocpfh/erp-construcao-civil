"""Configurações centrais: caminhos, perfis (RBAC) e catálogo de módulos."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    path = Path(os.environ.get("ERP_DATA_DIR", BASE_DIR / "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return Path(os.environ.get("ERP_DB_PATH", data_dir() / "erp_obra.db"))


def env_path() -> Path:
    return Path(os.environ.get("ERP_ENV_PATH", BASE_DIR / ".env"))


def media_dir() -> Path:
    path = data_dir() / "media"
    path.mkdir(parents=True, exist_ok=True)
    return path


PROJECT_NAME = "Residencial Bosque das Araucárias"
PROJECT_LOCATION = "Curitiba/PR"

ROLE_ADMIN = "Administrador"
ROLE_STOCK = "Almoxarife"
ROLE_VIEWER = "Visualizador"
ROLES = [ROLE_ADMIN, ROLE_STOCK, ROLE_VIEWER]

# Módulos controlados por checkbox no painel do Admin: chave -> (título, ícone)
MODULES: dict[str, tuple[str, str]] = {
    "painel": ("Painel Executivo", ":material/dashboard:"),
    "eap": ("WBS / EAP", ":material/account_tree:"),
    "cronograma": ("Cronograma & CPM", ":material/timeline:"),
    "rdo": ("Diário de Obra (RDO)", ":material/menu_book:"),
    "fiscal": ("Fiscal, Tributos & OCR", ":material/receipt_long:"),
    "estoque": ("Almoxarifado & Consumo", ":material/inventory_2:"),
    "midia": ("Memorial, Time-lapse & Flash", ":material/movie:"),
    "ambiental": ("Araucária & Repositório Legal", ":material/park:"),
    "ged": ("Central de Projetos (GED)", ":material/folder_open:"),
    "contatos": ("Agenda & Contatos", ":material/contacts:"),
}

# Páginas exclusivas do Administrador (nunca liberadas por checkbox)
ADMIN_PAGES: dict[str, tuple[str, str]] = {
    "usuarios": ("Gestão de Usuários", ":material/admin_panel_settings:"),
    "conexoes": ("Configurações de Conexão e Backup", ":material/cloud_sync:"),
}

DEFAULT_PERMISSIONS: dict[str, list[str]] = {
    ROLE_ADMIN: list(MODULES),
    ROLE_STOCK: ["estoque"],
    ROLE_VIEWER: [m for m in MODULES if m not in ("estoque",)],
}

WEATHER_OPTIONS = ["Ensolarado", "Nublado", "Chuva Fraca", "Chuva Forte"]
HEAVY_RAIN = "Chuva Forte"

WBS_STATUS = ["A Fazer", "Em Andamento", "Concluído"]
INVOICE_STATUS = ["Pendente", "Aprovada", "Rejeitada"]
GED_FOLDERS = ["Projetos", "Listas de Materiais", "Laudos/Licenças"]
LEGAL_CATEGORIES = ["Copel", "Sanepar", "Bombeiros", "Calçadas", "ABNT"]
