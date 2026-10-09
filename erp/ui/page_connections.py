"""Configurações de Conexão e Backup (somente Administrador): AWS S3 + FTP, gravadas criptografadas no .env."""
from __future__ import annotations

import streamlit as st

from erp import auth, db
from erp.config import env_path
from erp.settings_store import CONNECTION_FIELDS, load_connection_settings, mask, read_raw_env, write_env
from erp.services import mailer
from erp.storage import DualStorage, FTPBackend, S3Backend
from erp.ui.common import current_user, header


def render() -> None:
    if not auth.is_admin(current_user()):
        st.error("Acesso restrito ao Administrador.")
        st.stop()
    header("Configurações de Conexão e Backup",
           "AWS S3 = produção · FTP privado = backup físico estruturado (categoria/AAAA/MM). Segredos gravados criptografados no .env.")
    current = load_connection_settings()
    s3, ftp = S3Backend(current), FTPBackend(current)
    c = st.columns(2)
    c[0].metric("AWS S3 (Produção)", "Configurado" if s3.configured else "Não configurado")
    c[1].metric("FTP (Backup físico)", "Configurado" if ftp.configured else "Não configurado")

    with st.form("conn"):
        st.subheader("☁️ AWS S3")
        cc = st.columns(2)
        values = {}
        for i, key in enumerate(["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION", "S3_BUCKET", "S3_PREFIX"]):
            label, secret = CONNECTION_FIELDS[key]
            values[key] = cc[i % 2].text_input(
                label, value="" if secret else current.get(key, ""), type="password" if secret else "default",
                placeholder=f"atual: {mask(current.get(key, ''))}" if secret and current.get(key) else "",
                key=f"cfg_{key}")
        st.subheader("🗄️ Servidor FTP privado")
        cc = st.columns(2)
        for i, key in enumerate(["FTP_HOST", "FTP_PORT", "FTP_USER", "FTP_PASSWORD", "FTP_BASE_DIR"]):
            label, secret = CONNECTION_FIELDS[key]
            values[key] = cc[i % 2].text_input(
                label, value="" if secret else current.get(key, ""), type="password" if secret else "default",
                placeholder=f"atual: {mask(current.get(key, ''))}" if secret and current.get(key) else "",
                key=f"cfg_{key}")
        values["FTP_TLS"] = "1" if st.checkbox("Usar FTPS (TLS explícito)", current.get("FTP_TLS") == "1") else "0"
        st.subheader("✉️ E-mail (SMTP) — códigos de recuperação de senha e avisos")
        st.caption("Gmail: smtp.gmail.com, porta 587, starttls, e uma **senha de app** (Conta Google → Segurança → "
                   "Senhas de app). Outlook: smtp.office365.com, 587, starttls.")
        cc = st.columns(2)
        for i, key in enumerate(["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_SECURITY"]):
            label, secret = CONNECTION_FIELDS[key]
            values[key] = cc[i % 2].text_input(
                label, value="" if secret else current.get(key, ""), type="password" if secret else "default",
                placeholder=f"atual: {mask(current.get(key, ''))}" if secret and current.get(key) else "",
                key=f"cfg_{key}")
        st.caption("Campos secretos em branco mantêm o valor atual.")
        saved = st.form_submit_button("🔒 Salvar e criptografar no .env", type="primary")
    if saved:
        to_write = {k: v for k, v in values.items() if not (CONNECTION_FIELDS[k][1] and v == "")}
        path = write_env(to_write)
        st.success(f"Arquivo {path.name} reescrito com {len(to_write)} valor(es) criptografado(s) (Fernet).")
        st.rerun()

    c1, c2, c3 = st.columns(3)
    if c1.button("🔌 Testar Conexão FTP", type="primary", width="stretch"):
        ok, msg = FTPBackend(load_connection_settings()).test()
        (st.success if ok else st.error)(msg)
    if c2.button("☁️ Testar Conexão S3", width="stretch"):
        ok, msg = S3Backend(load_connection_settings()).test()
        (st.success if ok else st.error)(msg)
    if c3.button("🔁 Reenviar mídias pendentes", width="stretch",
                 help="Envia para S3/FTP as mídias que estão apenas no cache local."):
        _resync()

    with st.form("smtp_test"):
        to = st.text_input("Enviar e-mail de teste para")
        if st.form_submit_button("✉️ Testar envio de e-mail") and to:
            try:
                mailer.send(to, "Teste · ERP Obras", "Se você recebeu esta mensagem, o envio de e-mail está funcionando.")
                st.success(f"E-mail enviado para {to}.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Falha no envio: {exc}")

    with st.expander("Conteúdo atual do .env (criptografado)"):
        raw = read_raw_env()
        st.code("\n".join(f"{k}={v[:28]}…" if len(v) > 28 else f"{k}={v}" for k, v in raw.items()) or "(arquivo inexistente)")
        st.caption(f"Caminho: {env_path()} · chave mestra: variável ERP_MASTER_KEY / st.secrets ou data/.master.key")

    st.subheader("📊 Status do armazenamento duplo")
    df = db.query_df("SELECT category AS Categoria, COUNT(*) AS Arquivos, ROUND(SUM(size_bytes) / 1048576.0, 2) AS MB, "
                     "SUM(s3_status = 'ok') AS 'No S3', SUM(ftp_status = 'ok') AS 'No FTP' FROM media GROUP BY category")
    st.dataframe(df, hide_index=True, width="stretch")


def _resync() -> None:
    storage = DualStorage()
    if not (storage.s3.configured or storage.ftp.configured):
        st.warning("Configure S3 e/ou FTP antes de reenviar.")
        return
    rows = db.query("SELECT id, key, filename FROM media WHERE s3_status != 'ok' OR ftp_status != 'ok'")
    bar = st.progress(0.0, text="Sincronizando...")
    sent = 0
    for i, r in enumerate(rows):
        data = storage.load(r["key"])
        if data is None:
            continue
        res = storage.save(data, r["filename"] or "arquivo", key=r["key"])
        db.execute("UPDATE media SET s3_status = ?, ftp_status = ? WHERE id = ?", (res.s3, res.ftp, r["id"]))
        sent += res.remote_ok
        bar.progress((i + 1) / max(len(rows), 1), text=f"{i + 1}/{len(rows)}")
    st.success(f"{sent} de {len(rows)} mídia(s) sincronizada(s).")
