"""Envio de e-mail (SMTP) para códigos de recuperação de senha e avisos ao administrador."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr

from erp.settings_store import load_connection_settings


def configured(settings: dict | None = None) -> bool:
    s = settings if settings is not None else load_connection_settings()
    return bool(s.get("SMTP_HOST") and (s.get("SMTP_FROM") or s.get("SMTP_USER")))


def send(to: str, subject: str, body: str, settings: dict | None = None, timeout: int = 20) -> None:
    s = settings if settings is not None else load_connection_settings()
    if not configured(s):
        raise RuntimeError("Envio de e-mail (SMTP) não configurado.")
    msg = EmailMessage()
    msg["From"] = s.get("SMTP_FROM") or s["SMTP_USER"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    host, port = s["SMTP_HOST"], int(s.get("SMTP_PORT") or 587)
    security = (s.get("SMTP_SECURITY") or "starttls").lower()
    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(host, port, timeout=timeout)
    try:
        if security == "starttls":
            server.starttls(context=ssl.create_default_context())
        if s.get("SMTP_USER"):
            server.login(s["SMTP_USER"], s.get("SMTP_PASSWORD", ""))
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            server.close()


def valid_email(value: str) -> bool:
    addr = parseaddr(value or "")[1]
    return "@" in addr and "." in addr.split("@")[-1] and " " not in addr
