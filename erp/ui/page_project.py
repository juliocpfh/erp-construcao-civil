"""Dados do projeto, backup/restauração do banco e início de um projeto novo (somente Administrador)."""
from __future__ import annotations

from datetime import date, datetime

import streamlit as st

from erp import auth, db
from erp.security import password_policy_errors
from erp.services import backup, project
from erp.settings_store import load_connection_settings, mask, write_env
from erp.storage import FTPBackend
from erp.ui.common import current_user, header

CONFIRM_WORD = "APAGAR"


def render() -> None:
    if not auth.is_admin(current_user()):
        st.error("Acesso restrito ao Administrador.")
        st.stop()
    header("Projeto e Backup do Banco", "Dados da obra, cópia de segurança e início de um projeto novo.")
    tab_info, tab_backup, tab_new = st.tabs(["🏗️ Dados do projeto", "🗄️ Banco no FTP / Backup", "🆕 Novo projeto"])
    with tab_info:
        _project_form()
    with tab_backup:
        _backup()
    with tab_new:
        _new_project()


def _project_form() -> None:
    info = project.project_info()
    start = date.fromisoformat(info["start"]) if info["start"] else date.today()
    with st.form("project_info"):
        name = st.text_input("Nome da obra", info["name"])
        c1, c2 = st.columns(2)
        location = c1.text_input("Local (cidade/UF ou endereço)", info["location"])
        start = c2.date_input("Data de início da obra", start, format="DD/MM/YYYY")
        description = st.text_input("Descrição curta", info["description"])
        indirect = st.number_input("Custo indireto diário (R$/dia) — usado no custo do atraso", 0.0, 1e8,
                                   float(db.get_setting("daily_indirect_cost", "0") or 0), step=100.0)
        if st.form_submit_button("Salvar", type="primary"):
            for key, val in {"project_name": name.strip() or info["name"], "project_location": location.strip(),
                             "project_start": start.isoformat(), "project_description": description.strip(),
                             "daily_indirect_cost": indirect}.items():
                db.set_setting(key, val)
            st.success("Dados do projeto salvos.")
            st.rerun()
    st.caption("Ao mudar a data de início, o cronograma é recalculado; use **Congelar baseline** no Cronograma se "
               "quiser que a linha de base acompanhe.")


def _fmt_dt(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return value


def _fmt_info(info: dict) -> str:
    return (f"Obra **{info.get('project', '-')}** · {info.get('tasks', 0)} tarefas · {info.get('rdos', 0)} RDOs · "
            f"{info.get('invoices', 0)} NFs · último RDO {info.get('last_rdo') or '-'} · "
            f"{info.get('size', 0) / 1024:.0f} KB · SHA-256 `{(info.get('sha256') or '')[:12]}`")


def _backup() -> None:
    st.markdown("O banco trabalha no servidor do app e uma **cópia é enviada ao seu FTP** a cada alteração "
                "(no máximo a cada 2 minutos), conferida byte a byte. Ao reiniciar vazio, o app restaura a última versão.")
    for kind, msg in st.session_state.pop("ftp_flash", []):
        getattr(st, kind)(msg)
    _status_panel()
    st.divider()
    _ftp_form()
    st.divider()
    _remote_actions()
    st.divider()
    _local_file()


def _status_panel() -> None:
    stat = backup.status()
    settings = load_connection_settings()
    ftp = FTPBackend(settings)
    st.markdown("##### 📋 Situação")
    c = st.columns(3)
    with c[0].container(border=True):
        st.markdown("**🔌 Servidor FTP**")
        if ftp.configured:
            st.write(f"`{ftp.host}:{ftp.port}` · pasta `{ftp.base_dir}/backup-banco`")
        else:
            st.warning("FTP não configurado.")
        st.caption("Envio automático: " + ("🟢 ativo" if stat["armed"] else "🟠 aguardando confirmação"))
    with c[1].container(border=True):
        st.markdown("**☁️ Último backup enviado**")
        push = stat["last_push"]
        if push:
            where = ", ".join(k.upper() for k in ("ftp", "s3") if push.get(k) == "ok")
            st.success(f"{push['version']} · {_fmt_dt(push.get('created_at'))} · conferido ✅ ({where})")
            st.caption(_fmt_info(push))
        else:
            st.info("Nenhum backup enviado a partir deste banco.")
        if stat["last_error"]:
            st.error(stat["last_error"])
    with c[2].container(border=True):
        st.markdown("**♻️ Última versão restaurada**")
        rest = backup.last_restore()
        if rest:
            st.success(f"{rest['version']} · restaurada em {_fmt_dt(rest.get('restored_at'))}")
            st.caption(f"Origem: {rest.get('origin', '-')}. " + _fmt_info(rest))
        else:
            st.info("Este banco nunca foi restaurado de backup.")
    startup = stat["startup"]
    if startup and startup.get("configured"):
        (st.success if startup.get("ok") else st.warning)(
            f"Inicialização do app ({_fmt_dt(startup['at'])}): {startup['message']}")


def _ftp_form() -> None:
    st.markdown("##### ⚙️ Configuração e teste do FTP")
    st.caption("Mudou o endereço do FTP? Informe o novo, clique **Testar acesso** e depois **Salvar**. "
               "Campos de senha/usuário em branco mantêm o valor atual.")
    current = load_connection_settings()
    with st.form("ftp_cfg"):
        c1, c2, c3 = st.columns([3, 1, 1])
        host = c1.text_input("Endereço (IP ou domínio)", current.get("FTP_HOST", ""))
        port = c2.text_input("Porta", current.get("FTP_PORT", "21"))
        tls = c3.checkbox("FTPS (TLS)", current.get("FTP_TLS") == "1")
        c1, c2, c3 = st.columns(3)
        user = c1.text_input("Usuário", "", placeholder=f"atual: {mask(current.get('FTP_USER', ''))}" if current.get("FTP_USER") else "")
        pw = c2.text_input("Senha", "", type="password",
                           placeholder="atual: definida (deixe em branco para manter)" if current.get("FTP_PASSWORD") else "")
        base = c3.text_input("Pasta base no FTP", current.get("FTP_BASE_DIR", "/backup_obra"))
        b1, b2 = st.columns(2)
        test = b1.form_submit_button("🔌 Testar acesso (login + gravação)", width="stretch")
        save = b2.form_submit_button("💾 Testar e salvar", type="primary", width="stretch")
    values = {"FTP_HOST": host.strip(), "FTP_PORT": port.strip() or "21", "FTP_TLS": "1" if tls else "0",
              "FTP_BASE_DIR": base.strip() or "/backup_obra",
              "FTP_USER": user.strip() or current.get("FTP_USER", ""),
              "FTP_PASSWORD": pw or current.get("FTP_PASSWORD", "")}
    if test or save:
        with st.spinner("Conectando ao FTP..."):
            ok, msg = FTPBackend(values).test_write()
        if save and ok:
            write_env(values)
            flash = [("success", msg), ("success", "Configuração do FTP salva (criptografada).")]
            remote = backup.remote_manifest()
            if remote:
                flash.append(("info", f"Backup encontrado neste FTP: versão **{remote['version']}** de "
                                      f"{_fmt_dt(remote.get('created_at'))}. " + _fmt_info(remote)))
            st.session_state["ftp_flash"] = flash
            st.rerun()
        (st.success if ok else st.error)(msg)
        if save:
            st.warning("Nada foi salvo: corrija os dados até o teste passar.")
    with st.expander("Streamlit Cloud: guardar o FTP nos Secrets (obrigatório para restaurar após reinício)"):
        st.write("No Streamlit Cloud as configurações salvas aqui somem quando o app reinicia. Copie o bloco abaixo "
                 "em **Manage app → Settings → Secrets**, trocando a senha. Se o endereço do FTP mudar, atualize lá "
                 "também (ou use um domínio fixo, como um DNS dinâmico No-IP/DuckDNS, que acompanha a troca de IP).")
        st.code(f'''FTP_HOST = "{values['FTP_HOST']}"
FTP_PORT = "{values['FTP_PORT']}"
FTP_USER = "{values['FTP_USER']}"
FTP_PASSWORD = "SUA_SENHA_DO_FTP"
FTP_BASE_DIR = "{values['FTP_BASE_DIR']}"
FTP_TLS = "{values['FTP_TLS']}"
ERP_ADMIN_PASSWORD = "senha-inicial-do-admin"''', language="toml")


def _remote_actions() -> None:
    st.markdown("##### ☁️ Backup e restauração pelo servidor")
    if not backup.remote_configured():
        st.info("Configure o FTP acima para habilitar.")
        return
    remote = backup.remote_manifest()
    if remote:
        st.markdown(f"**Versão mais recente no servidor:** {remote['version']} · enviada em "
                    f"{_fmt_dt(remote.get('created_at'))}  \n" + _fmt_info(remote))
        if remote.get("version") not in backup.known_versions():
            st.warning("⚠️ A versão do servidor **não** é a deste banco (ex.: o app reiniciou sem conseguir "
                       "restaurar). O envio automático está pausado para não apagá-la. Restaure-a, ou confirme a "
                       "substituição no envio manual.")
    else:
        st.caption("Ainda não há backup no servidor.")
    c1, c2 = st.columns(2)
    with c1:
        overwrite = False
        if remote and remote.get("version") not in backup.known_versions():
            overwrite = st.checkbox("Substituir a versão do servidor pelo banco atual "
                                    "(a anterior continua no histórico)")
        if st.button("⬆️ Enviar backup agora", type="primary", width="stretch"):
            with st.spinner("Enviando e conferindo..."):
                res = backup.push_remote(force=overwrite)
            if res["ok"]:
                st.session_state["ftp_flash"] = [("success", res["message"])]
                st.rerun()
            st.error(res["message"])
    with c2:
        if remote and st.button("⬇️ Restaurar a última versão do servidor", width="stretch"):
            _do_restore(lambda: backup.restore_from_remote())
    versions = backup.list_versions() if remote else []
    if versions:
        with st.expander(f"Versões anteriores ({len(versions)})"):
            sel = st.selectbox("Versão", versions, format_func=lambda k: k.rsplit("/", 1)[-1])
            st.caption("Restaurar uma versão antiga pausa o envio automático até você enviar um backup manual.")
            if st.button("Restaurar esta versão"):
                _do_restore(lambda: backup.restore_from_remote(sel))


def _do_restore(fn) -> None:
    try:
        with st.spinner("Baixando e restaurando..."):
            info = fn()
    except ValueError as exc:
        st.error(str(exc))
        return
    st.session_state.clear()
    st.session_state["restore_msg"] = f"Versão {info['version']} restaurada. Faça login novamente."
    st.rerun()


def _local_file() -> None:
    st.markdown("##### 💻 Arquivo no seu computador")
    st.download_button("⬇️ Baixar cópia do banco", backup.snapshot(), file_name=backup.backup_filename(),
                       mime="application/x-sqlite3")
    up = st.file_uploader("Restaurar de um arquivo (.db) — substitui TODOS os dados atuais", type=["db", "sqlite", "sqlite3"])
    if up and st.button("Restaurar este arquivo", type="primary"):
        _do_restore(lambda: backup.restore(up.getvalue(), origin=f"arquivo {up.name}", version=up.name))


def _new_project() -> None:
    st.error("**Atenção:** iniciar um projeto novo APAGA todos os dados atuais (EAP, cronograma, RDOs, NFs, estoque, "
             "fotos, contatos e usuários). Baixe um backup antes, na aba ao lado, se quiser guardar.")
    with st.form("new_project"):
        name = st.text_input("Nome da nova obra *")
        c1, c2 = st.columns(2)
        location = c1.text_input("Local")
        start = c2.date_input("Data de início", date.today(), format="DD/MM/YYYY")
        description = st.text_input("Descrição curta")
        st.markdown("**Novo acesso do administrador** (usuário `admin`)")
        c1, c2 = st.columns(2)
        pw = c1.text_input("Nova senha do admin *", type="password")
        pw2 = c2.text_input("Confirmar senha *", type="password")
        confirm = st.text_input(f"Para confirmar, digite **{CONFIRM_WORD}**")
        submitted = st.form_submit_button("🆕 Apagar tudo e iniciar projeto novo", type="primary")
    if submitted:
        errors = []
        if not name.strip():
            errors.append("informe o nome da obra")
        if pw != pw2:
            errors.append("as senhas não conferem")
        errors += password_policy_errors(pw)
        if confirm.strip().upper() != CONFIRM_WORD:
            errors.append(f"digite {CONFIRM_WORD} para confirmar")
        if errors:
            st.error("Não foi possível: " + "; ".join(errors) + ".")
            return
        project.create_blank_project(name, location, start, description, admin_password=pw, must_change_password=False)
        if backup.remote_configured():  # o projeto antigo continua no histórico de versões do FTP
            backup.push_remote(force=True)
        st.session_state.clear()
        st.rerun()

    st.divider()
    st.markdown("##### 🎓 Carregar a simulação de demonstração")
    st.caption("Apaga tudo e recria o edifício de 10 pavimentos com dados fictícios (para treinamento). "
               "Senhas de teste no README.")
    with st.form("demo"):
        confirm = st.text_input(f"Digite **{CONFIRM_WORD}** para carregar a demonstração")
        if st.form_submit_button("Carregar demonstração"):
            if confirm.strip().upper() != CONFIRM_WORD:
                st.error(f"Digite {CONFIRM_WORD} para confirmar.")
            else:
                with st.spinner("Gerando simulação (~10 s)..."):
                    project.load_demo()
                backup.arm(False)  # a demonstração nunca sobrescreve o backup real no FTP
                st.session_state.clear()
                st.rerun()
