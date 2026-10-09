"""Contas de usuário: primeiro acesso (criar o administrador), solicitação de acesso, recuperação de senha.

Recuperação de senha, em ordem de preferência:
1. código de 6 dígitos enviado ao e-mail cadastrado (exige SMTP configurado), válido por 15 minutos;
2. pedido ao administrador, que define uma senha provisória;
3. administrador: código de recuperação gerado no primeiro acesso (guardado fora do sistema).
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from erp import auth, db
from erp.config import ROLE_ADMIN, ROLE_VIEWER
from erp.security import hash_password, password_policy_errors, verify_password
from erp.services import mailer

CODE_TTL_MIN = 15
MAX_ATTEMPTS = 5
GENERIC_RESET_MSG = ("Se o usuário existir e tiver e-mail cadastrado, um código foi enviado. "
                     "Confira a caixa de entrada (e o spam).")


class AccountError(ValueError):
    pass


def _check_password(password: str, confirm: str) -> None:
    if password != confirm:
        raise AccountError("As senhas não conferem.")
    errors = password_policy_errors(password)
    if errors:
        raise AccountError("Senha fraca: " + ", ".join(errors) + ".")


def _find(login_or_email: str) -> dict | None:
    key = (login_or_email or "").strip().lower()
    if not key:
        return None
    return db.query_one("SELECT * FROM users WHERE username = ? OR LOWER(email) = ? ORDER BY id LIMIT 1", (key, key))


def new_recovery_code() -> str:
    raw = secrets.token_hex(8).upper()
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


# --------------------------------------------------------------------------- primeiro acesso
def setup_pending() -> bool:
    """Instalação nova com o admin padrão ainda não configurado."""
    return db.get_setting("admin_setup_pending") == "1"


def complete_first_setup(username: str, full_name: str, email: str, password: str, confirm: str) -> str:
    """Configura o administrador da instalação nova. Retorna o código de recuperação (mostrar uma vez)."""
    if not setup_pending():
        raise AccountError("O administrador já foi configurado.")
    username = (username or "").strip().lower()
    if not username or " " in username:
        raise AccountError("Informe um login sem espaços.")
    if email and not mailer.valid_email(email):
        raise AccountError("E-mail inválido.")
    _check_password(password, confirm)
    admin = db.query_one("SELECT id FROM users WHERE role = ? ORDER BY id LIMIT 1", (ROLE_ADMIN,))
    clash = db.query_one("SELECT id FROM users WHERE username = ? AND id != ?", (username, admin["id"]))
    if clash:
        raise AccountError("Esse login já existe.")
    db.execute("UPDATE users SET username = ?, full_name = ?, email = ?, password_hash = ?, must_change_password = 0 "
               "WHERE id = ?", (username, full_name.strip() or username, email.strip() or None,
                                hash_password(password), admin["id"]))
    code = new_recovery_code()
    db.set_setting("admin_recovery_hash", hash_password(code))
    db.set_setting("admin_setup_pending", "0")
    return code


def regenerate_recovery_code() -> str:
    code = new_recovery_code()
    db.set_setting("admin_recovery_hash", hash_password(code))
    return code


def has_recovery_code() -> bool:
    return bool(db.get_setting("admin_recovery_hash"))


def reset_admin_with_recovery_code(username: str, code: str, password: str, confirm: str) -> str:
    """Administrador esqueceu a senha: código de recuperação + nova senha. Retorna um NOVO código."""
    stored = db.get_setting("admin_recovery_hash")
    user = _find(username)
    if not stored or not user or user["role"] != ROLE_ADMIN or not verify_password(code.strip().upper(), stored):
        raise AccountError("Usuário ou código de recuperação inválido.")
    _check_password(password, confirm)
    auth.change_password(user["id"], password)
    db.execute("UPDATE users SET active = 1 WHERE id = ?", (user["id"],))
    return regenerate_recovery_code()  # cada código vale uma vez


# --------------------------------------------------------------------------- solicitação de acesso
def request_access(username: str, full_name: str, email: str, password: str, confirm: str, note: str = "") -> int:
    username = (username or "").strip().lower()
    if not username or " " in username:
        raise AccountError("Informe um login sem espaços.")
    if not full_name.strip():
        raise AccountError("Informe seu nome.")
    if not mailer.valid_email(email):
        raise AccountError("Informe um e-mail válido (usado para recuperar a senha).")
    _check_password(password, confirm)
    if db.query_one("SELECT id FROM users WHERE username = ?", (username,)):
        raise AccountError("Esse login já existe. Escolha outro.")
    uid = auth.create_user(username, password, ROLE_VIEWER, full_name.strip(), permissions=[])
    db.execute("UPDATE users SET active = 0, status = 'pendente', email = ?, request_note = ? WHERE id = ?",
               (email.strip(), note.strip(), uid))
    _notify_admins(f"Nova solicitação de acesso: {full_name.strip()} ({username})",
                   f"{full_name.strip()} ({username}, {email.strip()}) pediu acesso ao ERP Obras.\n\n"
                   f"Mensagem: {note.strip() or '-'}\n\nAprove ou recuse em Administração → Gestão de Usuários.")
    return uid


def pending_requests() -> list[dict]:
    return db.query("SELECT id, username, full_name, email, request_note, created_at FROM users "
                    "WHERE status = 'pendente' ORDER BY id")


def approve_request(user_id: int, role: str, modules: list[str]) -> None:
    db.execute("UPDATE users SET status = 'ativo', active = 1 WHERE id = ? AND status = 'pendente'", (user_id,))
    auth.update_user(user_id, role=role)
    auth.set_permissions(user_id, modules)
    user = db.query_one("SELECT username, full_name, email FROM users WHERE id = ?", (user_id,))
    if user and user["email"]:
        _try_send(user["email"], "Seu acesso ao ERP Obras foi liberado",
                  f"Olá, {user['full_name']}.\n\nSeu acesso foi aprovado. Entre com o login '{user['username']}' "
                  "e a senha que você cadastrou.")


def reject_request(user_id: int) -> None:
    db.execute("DELETE FROM users WHERE id = ? AND status = 'pendente'", (user_id,))


# --------------------------------------------------------------------------- esqueci a senha
def request_reset_by_email(login_or_email: str) -> str:
    """Envia código por e-mail. A resposta é sempre a mesma (não revela se o usuário existe)."""
    if not mailer.configured():
        raise AccountError("O envio de e-mail não está configurado neste sistema. Use 'Pedir ao administrador'.")
    user = _find(login_or_email)
    if user and user["email"] and user["active"]:
        code = f"{secrets.randbelow(1_000_000):06d}"
        now = datetime.now()
        db.execute("UPDATE password_resets SET closed_at = ?, closed_by = 'substituído' "
                   "WHERE user_id = ? AND kind = 'email' AND closed_at IS NULL", (db.now_iso(), user["id"]))
        db.execute("INSERT INTO password_resets(user_id, kind, code_hash, expires_at, created_at) VALUES (?,?,?,?,?)",
                   (user["id"], "email", hash_password(code),
                    (now + timedelta(minutes=CODE_TTL_MIN)).isoformat(timespec="seconds"), db.now_iso()))
        mailer.send(user["email"], "Código para redefinir sua senha · ERP Obras",
                    f"Olá, {user['full_name']}.\n\nSeu código é: {code}\n\nEle vale por {CODE_TTL_MIN} minutos. "
                    "Se você não pediu, ignore este e-mail.")
    return GENERIC_RESET_MSG


def reset_with_code(login_or_email: str, code: str, password: str, confirm: str) -> None:
    user = _find(login_or_email)
    row = db.query_one("SELECT * FROM password_resets WHERE user_id = ? AND kind = 'email' AND closed_at IS NULL "
                       "ORDER BY id DESC LIMIT 1", (user["id"],)) if user else None
    if not row or datetime.fromisoformat(row["expires_at"]) < datetime.now() or row["attempts"] >= MAX_ATTEMPTS:
        raise AccountError("Código inválido ou expirado. Peça um novo código.")
    if not verify_password((code or "").strip(), row["code_hash"]):
        db.execute("UPDATE password_resets SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
        raise AccountError("Código incorreto.")
    _check_password(password, confirm)
    auth.change_password(user["id"], password)
    db.execute("UPDATE password_resets SET closed_at = ?, closed_by = 'usuário' WHERE id = ?", (db.now_iso(), row["id"]))


def request_reset_by_admin(login_or_email: str, note: str = "") -> str:
    user = _find(login_or_email)
    if user and user["status"] != "pendente":
        open_req = db.query_one("SELECT id FROM password_resets WHERE user_id = ? AND kind = 'admin' AND closed_at IS NULL",
                                (user["id"],))
        if not open_req:
            db.execute("INSERT INTO password_resets(user_id, kind, created_at) VALUES (?,?,?)",
                       (user["id"], "admin", db.now_iso()))
            _notify_admins(f"Pedido de nova senha: {user['username']}",
                           f"{user['full_name']} ({user['username']}) esqueceu a senha. {note}\n\n"
                           "Defina uma senha provisória em Administração → Gestão de Usuários.")
    return ("Pedido enviado ao administrador. Ele vai definir uma senha provisória e avisar você; "
            "no próximo login o sistema pede para criar uma senha nova.")


def open_admin_reset_requests() -> list[dict]:
    return db.query("SELECT r.id, r.user_id, r.created_at, u.username, u.full_name, u.email FROM password_resets r "
                    "JOIN users u ON u.id = r.user_id WHERE r.kind = 'admin' AND r.closed_at IS NULL ORDER BY r.id")


def resolve_admin_reset(request_id: int, admin_username: str) -> str:
    """Define senha provisória para o pedido e o encerra. Retorna a senha provisória (e tenta mandar por e-mail)."""
    req = db.query_one("SELECT * FROM password_resets WHERE id = ?", (request_id,))
    if not req:
        raise AccountError("Pedido não encontrado.")
    temp = f"Obra@{secrets.randbelow(900000) + 100000}"
    auth.set_temporary_password(req["user_id"], temp)
    db.execute("UPDATE password_resets SET closed_at = ?, closed_by = ? WHERE id = ?",
               (db.now_iso(), admin_username, request_id))
    user = db.query_one("SELECT full_name, username, email FROM users WHERE id = ?", (req["user_id"],))
    if user and user["email"]:
        _try_send(user["email"], "Senha provisória · ERP Obras",
                  f"Olá, {user['full_name']}.\n\nSua senha provisória é: {temp}\n"
                  f"Entre com o login '{user['username']}'; o sistema vai pedir uma senha nova.")
    return temp


def pending_count() -> int:
    return len(pending_requests()) + len(open_admin_reset_requests())


# --------------------------------------------------------------------------- perfil
def update_profile(user_id: int, full_name: str, email: str) -> None:
    if email and not mailer.valid_email(email):
        raise AccountError("E-mail inválido.")
    db.execute("UPDATE users SET full_name = ?, email = ? WHERE id = ?", (full_name.strip(), email.strip() or None, user_id))


def change_own_password(user_id: int, current: str, password: str, confirm: str) -> None:
    row = db.query_one("SELECT password_hash FROM users WHERE id = ?", (user_id,))
    if not row or not verify_password(current, row["password_hash"]):
        raise AccountError("Senha atual incorreta.")
    _check_password(password, confirm)
    auth.change_password(user_id, password)


def _notify_admins(subject: str, body: str) -> None:
    for a in db.query("SELECT email FROM users WHERE role = ? AND active = 1 AND email IS NOT NULL", (ROLE_ADMIN,)):
        _try_send(a["email"], subject, body)


def _try_send(to: str, subject: str, body: str) -> bool:
    try:
        if mailer.configured():
            mailer.send(to, subject, body)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False
