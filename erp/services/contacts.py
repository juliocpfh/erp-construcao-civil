"""Agenda: importação de vCard (.vcf 2.1/3.0/4.0) e timeline do histórico de cada envolvido."""
from __future__ import annotations

import quopri
import re
import unicodedata

from erp import db


def _unfold(text: str) -> list[str]:
    """Desfaz a quebra de linha do padrão vCard (linhas iniciadas por espaço/tab)."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif lines and lines[-1].endswith("=") and "QUOTED-PRINTABLE" in lines[-1].upper():
            lines[-1] = lines[-1][:-1] + raw  # soft line break do quoted-printable
        else:
            lines.append(raw)
    return lines


def _decode_value(params: str, value: str) -> str:
    if "QUOTED-PRINTABLE" in params.upper():
        charset = "utf-8"
        m = re.search(r"CHARSET=([\w-]+)", params, flags=re.IGNORECASE)
        if m:
            charset = m.group(1)
        value = quopri.decodestring(value.encode()).decode(charset, errors="replace")
    return value.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").strip()


def parse_vcf(content: str | bytes) -> list[dict]:
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = content.decode("latin-1")
    cards: list[dict] = []
    current: dict | None = None
    for line in _unfold(content):
        if not line.strip():
            continue
        upper = line.upper()
        if upper.startswith("BEGIN:VCARD"):
            current = {"name": "", "phones": [], "emails": [], "organization": "", "title": ""}
            continue
        if upper.startswith("END:VCARD"):
            if current is not None:
                if not current["name"]:
                    current["name"] = current.get("_n", "") or (current["emails"][0] if current["emails"] else "")
                current.pop("_n", None)
                current["phone"] = current["phones"][0] if current["phones"] else ""
                current["email"] = current["emails"][0] if current["emails"] else ""
                if current["name"]:
                    cards.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        head, _, value = line.partition(":")
        prop, _, params = head.partition(";")
        prop = prop.split(".")[-1].upper()  # remove prefixos de grupo (item1.TEL)
        value = _decode_value(params, value)
        if prop == "FN":
            current["name"] = value
        elif prop == "N":
            parts = [p.strip() for p in value.split(";")]
            given = " ".join(p for p in parts[1:3] if p)
            current["_n"] = f"{given} {parts[0]}".strip() if parts else ""
        elif prop == "TEL":
            phone = re.sub(r"[^\d+]", "", value)
            if phone:
                current["phones"].append(phone)
        elif prop == "EMAIL":
            current["emails"].append(value.lower())
        elif prop == "ORG":
            current["organization"] = value.split(";")[0]
        elif prop in ("TITLE", "ROLE"):
            current["title"] = current["title"] or value
    return cards


def normalize(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def format_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]
    if len(digits) == 11:
        return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return phone


def import_contacts(cards: list[dict], category: str = "Importado vCard") -> dict:
    """Cria ou atualiza contatos (casando por e-mail ou nome) e vincula NFs pelo nome do emitente."""
    created = updated = linked = 0
    existing = db.query("SELECT id, name, email, organization FROM contacts")
    by_email = {c["email"].lower(): c for c in existing if c["email"]}
    by_name = {normalize(c["name"]): c for c in existing}
    with db.transaction() as conn:
        for card in cards:
            match = by_email.get(card.get("email", "")) or by_name.get(normalize(card["name"]))
            phone = format_phone(card.get("phone", ""))
            if match:
                conn.execute(
                    "UPDATE contacts SET phone = COALESCE(NULLIF(?, ''), phone), email = COALESCE(NULLIF(?, ''), email), "
                    "organization = COALESCE(NULLIF(?, ''), organization), title = COALESCE(NULLIF(?, ''), title) "
                    "WHERE id = ?",
                    (phone, card.get("email", ""), card.get("organization", ""), card.get("title", ""), match["id"]),
                )
                contact_id = match["id"]
                updated += 1
            else:
                cur = conn.execute(
                    "INSERT INTO contacts(name, phone, email, organization, title, category, source, created_at) "
                    "VALUES (?,?,?,?,?,?, 'vcf', ?)",
                    (card["name"], phone, card.get("email", ""), card.get("organization", ""),
                     card.get("title", ""), category, db.now_iso()),
                )
                contact_id = cur.lastrowid
                created += 1
            org = normalize(card.get("organization"))
            if org:
                for inv in conn.execute("SELECT id, supplier_name FROM invoices WHERE supplier_contact_id IS NULL").fetchall():
                    if normalize(inv["supplier_name"]) == org:
                        conn.execute("UPDATE invoices SET supplier_contact_id = ? WHERE id = ?", (contact_id, inv["id"]))
                        linked += 1
    return {"created": created, "updated": updated, "linked_invoices": linked}


def contact_timeline(contact_id: int) -> list[dict]:
    """Histórico do envolvido: tarefas que gerencia, RDOs que assinou e NFs que emitiu."""
    events: list[dict] = []
    for t in db.query(
        "SELECT code, name, baseline_start, baseline_finish, progress FROM tasks WHERE responsible_contact_id = ?",
        (contact_id,),
    ):
        events.append({"date": t["baseline_start"], "end": t["baseline_finish"], "type": "Tarefa gerenciada",
                       "description": f"{t['code']} - {t['name']} ({t['progress']:.0f}% executado)"})
    for w in db.query("SELECT code, name, status FROM wbs WHERE responsible_contact_id = ?", (contact_id,)):
        events.append({"date": None, "end": None, "type": "Entrega (EAP)",
                       "description": f"{w['code']} - {w['name']} [{w['status']}]"})
    for r in db.query("SELECT date, weather, occurrences FROM rdo WHERE signed_by_contact_id = ? ORDER BY date",
                      (contact_id,)):
        events.append({"date": r["date"], "end": None, "type": "RDO assinado",
                       "description": f"RDO {r['date']} - {r['weather']}" + (f" | {r['occurrences'][:80]}" if r["occurrences"] else "")})
    for n in db.query(
        "SELECT number, issue_date, total_value, status FROM invoices WHERE supplier_contact_id = ? ORDER BY issue_date",
        (contact_id,),
    ):
        events.append({"date": n["issue_date"], "end": None, "type": "NF emitida",
                       "description": f"NF {n['number']} - R$ {n['total_value']:,.2f} ({n['status']})",
                       "value": n["total_value"]})
    events.sort(key=lambda e: (e["date"] is None, e["date"] or ""))
    return events
