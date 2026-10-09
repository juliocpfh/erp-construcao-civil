"""Componentes visuais compartilhados (CSS responsivo, alertas piscantes, KPIs)."""
from __future__ import annotations

import html

import streamlit as st

from erp import auth
from erp.services.finance import brl

CSS = """
<style>
:root { --erp-red: #C0392B; --erp-blue: #1F4E79; }
.block-container { padding-top: 1.6rem; padding-bottom: 2rem; }
@keyframes erp-blink { 0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(192,57,43,.7);} 50% { opacity: .35; box-shadow: 0 0 18px 6px rgba(192,57,43,.45);} }
.erp-alert { border-radius: 10px; padding: .8rem 1rem; margin: .4rem 0; font-weight: 600; line-height: 1.35; }
.erp-alert.danger { background: #C0392B; color: #fff; }
.erp-alert.warning { background: #F39C12; color: #1b1b1b; }
.erp-alert.blink { animation: erp-blink 1.1s ease-in-out infinite; }
.erp-alert small { font-weight: 400; display: block; margin-top: .2rem; opacity: .95; }
.erp-card { border: 1px solid rgba(128,128,128,.35); border-radius: 10px; padding: .6rem .75rem; margin-bottom: .5rem; }
.erp-card .t { font-weight: 600; }
.erp-card .s { font-size: .82rem; opacity: .8; }
.erp-badge { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: .75rem; font-weight: 600; }
.erp-badge.crit { background: #C0392B; color: #fff; }
.erp-badge.ok { background: #1E8449; color: #fff; }
.erp-timeline { border-left: 3px solid var(--erp-blue); padding-left: .9rem; margin-left: .4rem; }
.erp-timeline .ev { margin-bottom: .55rem; }
.erp-timeline .ev b { color: var(--erp-blue); }
@media (max-width: 640px) {
  .block-container { padding-left: .6rem; padding-right: .6rem; }
  h1 { font-size: 1.45rem !important; }
  h2 { font-size: 1.2rem !important; }
  [data-testid="stMetricValue"] { font-size: 1.15rem !important; }
  .erp-alert { font-size: .9rem; }
}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def current_user() -> dict | None:
    return st.session_state.get("user")


def can_edit() -> bool:
    return auth.can_edit(current_user())


def username() -> str:
    user = current_user()
    return user["username"] if user else "-"


def header(title: str, subtitle: str = "") -> None:
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def blink_alert(title: str, detail: str = "", level: str = "danger", blink: bool = True) -> None:
    cls = f"erp-alert {level}{' blink' if blink else ''}"
    body = f"{html.escape(title)}" + (f"<small>{html.escape(detail)}</small>" if detail else "")
    st.markdown(f'<div class="{cls}">{body}</div>', unsafe_allow_html=True)


def read_only_notice() -> None:
    st.info("Perfil **Visualizador**: acesso somente leitura neste módulo.", icon=":material/visibility:")


def money(v: float | None) -> str:
    return brl(v)


def money_short(v: float | None) -> str:
    """R$ compacto para cartões de KPI (cabe no celular): R$ 8,54 mi / R$ 350,2 mil."""
    if v is None:
        return "-"
    a = abs(v)
    if a >= 1e6:
        return "R$ " + f"{v / 1e6:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " mi"
    if a >= 1e3:
        return "R$ " + f"{v / 1e3:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") + " mil"
    return brl(v)


def fmt_num(v: float, decimals: int = 0) -> str:
    s = f"{v:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def card(title: str, subtitle: str = "", badge: str = "", badge_cls: str = "") -> None:
    b = f' <span class="erp-badge {badge_cls}">{html.escape(badge)}</span>' if badge else ""
    st.markdown(
        f'<div class="erp-card"><div class="t">{html.escape(title)}{b}</div>'
        f'<div class="s">{html.escape(subtitle)}</div></div>',
        unsafe_allow_html=True,
    )


def has_schedule() -> bool:
    from erp import db

    return bool(db.query_one("SELECT COUNT(*) AS n FROM tasks")["n"])


def empty_project_guide(context: str = "") -> None:
    """Orientação exibida enquanto o projeto não tem cronograma cadastrado."""
    st.info((context + "\n\n" if context else "") +
            "**Projeto novo — siga esta ordem para cadastrar a obra (cada etapa é salva na hora):**\n\n"
            "1. **Usuários** (Administração): crie os usuários da equipe e marque as permissões.\n"
            "2. **WBS / EAP**: cadastre as etapas e entregas da obra.\n"
            "3. **Cronograma**: cadastre as tarefas (duração, custo, predecessoras) e congele a **baseline**.\n"
            "4. **Almoxarifado**: cadastre os materiais (unidade, lead time, estoque mínimo).\n"
            "5. **Agenda**: importe ou cadastre os contatos (fornecedores, equipe, órgãos).\n"
            "6. No dia a dia: **RDO**, **NFs**, fotos e checklist ambiental alimentam os indicadores.\n\n"
            "Os indicadores (IDC, IDP, Curva S, Gantt) aparecem assim que houver tarefas no cronograma.")


FTP_PROBLEM_TITLES = {
    "unreachable": "🔌 SEM CONEXÃO COM O FTP — o endereço pode ter mudado",
    "auth": "🔑 O FTP RECUSOU O LOGIN — usuário ou senha mudaram",
    "write": "🚫 O FTP NÃO PERMITE GRAVAR na pasta de backup",
    "blocked": "⚠️ BACKUP PAUSADO — o FTP tem uma versão diferente do banco",
}


def ftp_steps(problem: dict) -> list[str]:
    """Passo a passo para resolver o problema de conexão com o FTP, conforme o tipo de falha."""
    kind = problem["kind"]
    page = "**Administração → Projeto e Backup do Banco → aba Banco no FTP / Backup**"
    if kind == "blocked":
        return [
            f"Abra {page} e veja o quadro **Versão mais recente no servidor** (data, obra, nº de tarefas/RDOs).",
            "Se a versão do servidor é a correta (a obra de verdade): clique **⬇️ Restaurar a última versão do "
            "servidor**. O app volta com todos os dados.",
            "Se o banco atual é o correto: marque **Substituir a versão do servidor** e clique **⬆️ Enviar backup "
            "agora** (a versão antiga continua no histórico do FTP).",
            "Confira que o quadro **Último backup enviado** ficou verde com “conferido ✅”.",
        ]
    first = {
        "unreachable": "Descubra o endereço atual do FTP: no painel da hospedagem do FTP, ou, se o FTP fica na sua "
                       "casa/escritório, o IP público atual da internet de lá (abra meuip.com.br num computador "
                       "dessa rede). Confira também se o servidor/roteador está ligado.",
        "auth": "Confirme o usuário e a senha atuais do FTP (painel da hospedagem ou quem administra o servidor).",
        "write": "Peça a quem administra o FTP permissão de gravação para esse usuário na pasta base "
                 "(ex.: /backup_obra), ou escolha outra pasta em que ele possa gravar.",
    }[kind]
    field = {"unreachable": "**Endereço** (e a **Porta**, se mudou)", "auth": "**Usuário** e **Senha**",
             "write": "**Pasta base no FTP**"}[kind]
    steps = [
        first,
        f"Abra {page}.",
        f"Em **Configuração e teste do FTP**, atualize {field} e clique **🔌 Testar acesso**. Só avance quando "
        "aparecer a mensagem verde **“Gravação e leitura confirmadas”**.",
        "Clique **💾 Testar e salvar**.",
    ]
    if problem.get("startup"):
        steps.append("**Importante:** o app reiniciou sem conseguir baixar o banco. **Não lance dados antes deste "
                     "passo:** clique **⬇️ Restaurar a última versão do servidor** e confira o quadro **Última versão "
                     "restaurada** (data e obra). Depois faça login de novo.")
    else:
        steps.append("Clique **⬆️ Enviar backup agora** e confira que o quadro **Último backup enviado** ficou verde "
                     "com “conferido ✅”.")
    if kind != "write":
        steps.append("Se o app roda no **Streamlit Cloud**: abra **share.streamlit.io → seu app → ⋮ → Settings → "
                     "Secrets**, corrija `FTP_HOST`/`FTP_PORT`" + ("/`FTP_USER`/`FTP_PASSWORD`" if kind == "auth" else "")
                     + " e clique **Save**. Sem isso, o próximo reinício do app volta a usar o dado antigo.")
    if kind == "unreachable":
        steps.append("Para não passar por isso de novo: crie um endereço fixo gratuito (DuckDNS ou No-IP) que "
                     "acompanha a troca de IP e use-o no lugar do número do IP.")
    return steps


def ftp_problem_alert(problem: dict | None, admin: bool, fix_page=None, expanded: bool = False) -> None:
    """Alerta piscante em todas as telas quando a conexão com o FTP do banco falha, com o passo a passo."""
    if not problem:
        return
    since = problem["since"].strftime("%d/%m %H:%M") if problem.get("since") else ""
    title = FTP_PROBLEM_TITLES.get(problem["kind"], FTP_PROBLEM_TITLES["unreachable"])
    if not admin:
        detail = ("O app reiniciou sem conseguir carregar o banco de dados do servidor: NÃO lance dados até o "
                  "administrador resolver. " if problem.get("startup") else
                  "Os lançamentos continuam sendo gravados, mas a cópia de segurança no FTP está parada. ")
        blink_alert(title, detail + "Avise o administrador do sistema.", level="danger" if problem.get("startup") else "warning")
        return
    detail = (f"Desde {since}. " if since else "") + (
        "O app reiniciou e NÃO conseguiu restaurar o banco do FTP." if problem.get("startup")
        else "Os dados continuam salvos aqui, mas a cópia de segurança no FTP está parada até você corrigir.")
    blink_alert(title, detail)
    with st.expander("🛠️ Passo a passo para corrigir", expanded=expanded):
        st.markdown("\n".join(f"{i}. {s}" for i, s in enumerate(ftp_steps(problem), 1)))
        st.caption(f"Erro técnico: {problem.get('detail', '-')}")
        if fix_page is not None:
            st.page_link(fix_page, label="Ir para Banco no FTP / Backup", icon=":material/settings_backup_restore:")
