"""Itens da NF -> materiais: leitura dos itens (XML da NF-e ou texto/OCR) e cadastro automático.

Cada item é casado com um material existente por (1) código do produto do mesmo fornecedor já visto,
(2) descrição já vista, (3) descrição parecida (>= 85%). Sem correspondência, o material é cadastrado
automaticamente com a descrição, a unidade e o preço da NF, e o "apelido" fica guardado para as próximas notas.
"""
from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import date, datetime
from difflib import SequenceMatcher

from erp import db

UNITS = {
    "UN": "un", "UND": "un", "UNID": "un", "UNIDADE": "un", "PC": "pç", "PÇ": "pç", "PCA": "pç", "PECA": "pç",
    "M": "m", "MT": "m", "MTS": "m", "ML": "m", "M2": "m²", "M²": "m²", "M3": "m³", "M³": "m³",
    "KG": "kg", "KGS": "kg", "G": "g", "SC": "sc", "SACO": "sc", "SCO": "sc", "CX": "cx", "CAIXA": "cx",
    "L": "L", "LT": "L", "LTS": "L", "LITRO": "L", "TON": "t", "T": "t", "TN": "t", "MIL": "mil", "MILHEIRO": "mil",
    "BR": "br", "BARRA": "br", "RL": "rl", "ROLO": "rl", "GL": "gl", "GALAO": "gl", "LATA": "lt", "KIT": "kit",
    "CH": "ch", "CHAPA": "ch", "PAR": "par", "JG": "jg", "JOGO": "jg", "VB": "vb", "VERBA": "vb", "TB": "tb",
}
MATCH_THRESHOLD = 0.85
_NUM = r"\d{1,3}(?:\.\d{3})*(?:,\d{1,4})?|\d+(?:[.,]\d{1,4})?"


@dataclass
class NFItem:
    description: str
    quantity: float
    unit: str
    unit_price: float
    total: float = 0.0
    supplier_code: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9,./x ]+", " ", text)).strip()


def norm_unit(unit: str) -> str:
    u = (unit or "").strip().upper().rstrip(".")
    return UNITS.get(u, (unit or "un").strip().lower() or "un")


def _num(raw: str) -> float:
    raw = raw.strip()
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", raw):
        raw = raw.replace(".", "")
    return float(raw)


# --------------------------------------------------------------------------- XML da NF-e
def parse_nfe_xml(data: bytes) -> dict:
    """Lê o XML da NF-e (modelo 55/65): emitente, número, emissão, total e itens com exatidão."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"XML inválido: {exc}") from exc

    def find(node, path):
        found = node.find(".//{*}" + path.replace("/", "/{*}"))
        return found.text.strip() if found is not None and found.text else ""

    inf = root.find(".//{*}infNFe")
    if inf is None:
        raise ValueError("O arquivo não é um XML de NF-e (infNFe não encontrado).")
    emit = inf.find("{*}emit")
    cnpj = find(emit, "CNPJ") or find(emit, "CPF")
    if len(cnpj) == 14:
        cnpj = f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"
    issued_raw = find(inf, "ide/dhEmi") or find(inf, "ide/dEmi")
    try:
        issued = datetime.fromisoformat(issued_raw).date() if "T" in issued_raw else date.fromisoformat(issued_raw[:10])
    except ValueError:
        issued = None
    items = []
    for det in inf.findall("{*}det"):
        prod = det.find("{*}prod")
        items.append(NFItem(
            description=find(prod, "xProd"), quantity=float(find(prod, "qCom") or 0), unit=norm_unit(find(prod, "uCom")),
            unit_price=float(find(prod, "vUnCom") or 0), total=float(find(prod, "vProd") or 0),
            supplier_code=find(prod, "cProd")))
    iss = find(inf, "total/ISSQNtot/vISS")
    fields = {
        "fornecedor": find(emit, "xNome") or None, "cnpj": cnpj or None, "numero": find(inf, "ide/nNF") or None,
        "valor": float(find(inf, "total/ICMSTot/vNF") or 0) or None, "emissao": issued,
        "iss": float(iss) if iss else None, "inss": None,
    }
    return {"fields": fields, "items": items, "engine": "XML da NF-e"}


# --------------------------------------------------------------------------- texto / OCR
def parse_items_text(text: str) -> list[NFItem]:
    """Heurística para itens no texto da DANFE (OCR ou colado).

    Aceita 'descrição qtd unidade valor_unit [total]' e 'descrição unidade qtd valor_unit [total]'
    (ordem usual da DANFE), ignorando código, NCM, CST e CFOP no início/meio da linha.
    """
    units = "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True))
    pat_qty_first = re.compile(rf"^(?P<desc>.+?)\s+(?P<qty>{_NUM})\s*(?P<unit>{units})\.?\s+(?:R\$\s*)?(?P<price>{_NUM})"
                               rf"(?:\s+(?:R\$\s*)?(?P<total>{_NUM}))?\s*$", re.IGNORECASE)
    pat_unit_first = re.compile(rf"^(?P<desc>.+?)\s+(?P<unit>{units})\.?\s+(?P<qty>{_NUM})\s+(?:R\$\s*)?(?P<price>{_NUM})"
                                rf"(?:\s+(?:R\$\s*)?(?P<total>{_NUM}))?\s*$", re.IGNORECASE)
    skip = re.compile(r"TOTAL|VALOR|BASE DE C|ICMS|FRETE|DESCONTO|CNPJ|EMISS|DESCRI|SUBTOTAL|TRIBUT|IMPOSTO", re.I)
    items = []
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" |;")
        if len(line) < 6 or skip.search(line):
            continue
        m = pat_qty_first.match(line) or pat_unit_first.match(line)
        if not m:
            continue
        desc = m.group("desc")
        code = ""
        lead = re.match(r"^(\d{3,14})\s+(.*)$", desc)
        if lead and re.search(r"[A-Za-zÀ-ú]", lead.group(2)):
            code, desc = lead.group(1), lead.group(2)
        desc = re.sub(r"\s+\d{8}(\s+\d{3,4}){0,2}\s*$", "", desc).strip(" -")  # NCM / CST / CFOP
        try:
            qty, price = _num(m.group("qty")), _num(m.group("price"))
            total = _num(m.group("total")) if m.group("total") else round(qty * price, 2)
        except ValueError:
            continue
        if qty <= 0 or price <= 0 or not re.search(r"[A-Za-zÀ-ú]{3}", desc):
            continue
        items.append(NFItem(desc, qty, norm_unit(m.group("unit")), price, total, code))
    return items


# --------------------------------------------------------------------------- casamento e cadastro
def _cnpj_key(cnpj: str | None) -> str:
    return re.sub(r"\D", "", cnpj or "")


def match_material(item: NFItem | dict, supplier_cnpj: str | None = None) -> tuple[int | None, str]:
    """Retorna (material_id, motivo) ou (None, '') se não houver correspondência."""
    it = item if isinstance(item, dict) else item.as_dict()
    desc_n, cnpj = norm(it["description"]), _cnpj_key(supplier_cnpj)
    if it.get("supplier_code") and cnpj:
        row = db.query_one("SELECT material_id FROM material_aliases WHERE supplier_cnpj = ? AND supplier_code = ?",
                           (cnpj, it["supplier_code"]))
        if row:
            return row["material_id"], "código do fornecedor"
    row = db.query_one("SELECT material_id FROM material_aliases WHERE description_norm = ?", (desc_n,))
    if row:
        return row["material_id"], "descrição já recebida"
    best, best_score = None, 0.0
    for m in db.query("SELECT id, name, unit FROM materials"):
        score = SequenceMatcher(None, desc_n, norm(m["name"])).ratio()
        if norm_unit(m["unit"]) != norm_unit(it.get("unit", "")):
            score -= 0.1
        if score > best_score:
            best, best_score = m["id"], score
    if best is not None and best_score >= MATCH_THRESHOLD:
        return best, f"descrição parecida ({best_score:.0%})"
    return None, ""


def next_material_code() -> str:
    codes = {r["code"] for r in db.query("SELECT code FROM materials")}
    n = len(codes) + 1
    while f"M{n:02d}" in codes:
        n += 1
    return f"M{n:02d}"


def remember_alias(material_id: int, item: dict, supplier_cnpj: str | None) -> None:
    db.execute("INSERT OR IGNORE INTO material_aliases(material_id, supplier_cnpj, supplier_code, description_norm) "
               "VALUES (?,?,?,?)", (material_id, _cnpj_key(supplier_cnpj), item.get("supplier_code") or "",
                                     norm(item["description"])))


def create_material_from_item(item: dict, lead_time_days: int = 7) -> int:
    name = re.sub(r"\s+", " ", item["description"]).strip()
    name = name[:1].upper() + name[1:]
    return db.execute(
        "INSERT INTO materials(code, name, unit, unit_cost, lead_time_days, min_stock, origin, created_at) "
        "VALUES (?,?,?,?,?,0,'nf',?)",
        (next_material_code(), name, norm_unit(item.get("unit", "un")), float(item.get("unit_price") or 0),
         lead_time_days, db.now_iso()))


def resolve_items(items: list[dict], supplier_cnpj: str | None) -> list[dict]:
    """Para cada item: material_id (existente ou None = será cadastrado) e motivo, para pré-visualizar."""
    out = []
    for it in items:
        mid, why = match_material(it, supplier_cnpj)
        out.append({**it, "material_id": mid, "match": why or "novo material (cadastro automático)"})
    return out


def register_items(invoice_id: int, items: list[dict], supplier_cnpj: str | None) -> dict:
    """Grava os itens da NF; cadastra materiais novos automaticamente. Retorna contagem de criados/vinculados."""
    created, linked = [], 0
    for it in items:
        if not it.get("description") or not float(it.get("quantity") or 0):
            continue
        mid = it.get("material_id")
        if not mid:
            mid, _ = match_material(it, supplier_cnpj)
        if not mid:
            mid = create_material_from_item(it)
            created.append(mid)
        else:
            linked += 1
            if it.get("unit_price"):
                db.execute("UPDATE materials SET unit_cost = ? WHERE id = ?", (float(it["unit_price"]), mid))
        remember_alias(mid, it, supplier_cnpj)
        db.execute("INSERT INTO invoice_items(invoice_id, material_id, quantity, unit_price, description, supplier_code) "
                   "VALUES (?,?,?,?,?,?)", (invoice_id, mid, float(it["quantity"]), float(it.get("unit_price") or 0),
                                            it["description"], it.get("supplier_code") or ""))
    return {"created": len(created), "linked": linked, "created_ids": created}
