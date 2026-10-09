"""Controle de acesso baseado em papéis (RBAC) com permissões dinâmicas por usuário."""
from __future__ import annotations

from erp.config import ADMIN_PAGES, DEFAULT_PERMISSIONS, DOC_AREAS, MODULES, ROLE_ADMIN, ROLE_VIEWER, ROLES
from erp.db import connect, execute, now_iso, query, query_one, transaction
from erp.security import hash_password, password_policy_errors, verify_password


class AuthError(ValueError):
    pass


def create_user(username: str, password: str, role: str, full_name: str = "",
                must_change_password: bool = False, permissions: list[str] | None = None,
                contact_id: int | None = None) -> int:
    username = username.strip().lower()
    if not username:
        raise AuthError("Usuário obrigatório.")
    if role not in ROLES:
        raise AuthError(f"Perfil inválido: {role}")
    if query_one("SELECT id FROM users WHERE username = ?", (username,)):
        raise AuthError(f"Usuário '{username}' já existe.")
    perms = permissions if permissions is not None else DEFAULT_PERMISSIONS[role]
    with transaction() as conn:
        cur = conn.execute(
            "INSERT INTO users(username, full_name, password_hash, role, must_change_password, contact_id, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (username, full_name or username, hash_password(password), role,
             int(must_change_password), contact_id, now_iso()),
        )
        user_id = int(cur.lastrowid)
        conn.executemany(
            "INSERT INTO user_permissions(user_id, module) VALUES (?, ?)",
            [(user_id, m) for m in perms if m in MODULES],
        )
    return user_id


def authenticate(username: str, password: str) -> dict | None:
    user = query_one("SELECT * FROM users WHERE username = ?", (username.strip().lower(),))
    if not user or not user["active"]:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    user.pop("password_hash", None)
    return user


def get_user(user_id: int) -> dict | None:
    user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if user:
        user.pop("password_hash", None)
    return user


def list_users() -> list[dict]:
    users = query("SELECT id, username, full_name, role, must_change_password, active, created_at FROM users ORDER BY id")
    perms = query("SELECT user_id, module FROM user_permissions")
    by_user: dict[int, set[str]] = {}
    for p in perms:
        by_user.setdefault(p["user_id"], set()).add(p["module"])
    for u in users:
        u["permissions"] = by_user.get(u["id"], set())
    return users


def get_permissions(user_id: int) -> set[str]:
    return {r["module"] for r in query("SELECT module FROM user_permissions WHERE user_id = ?", (user_id,))}


def set_permissions(user_id: int, modules: list[str] | set[str]) -> None:
    with transaction() as conn:
        conn.execute("DELETE FROM user_permissions WHERE user_id = ?", (user_id,))
        conn.executemany(
            "INSERT INTO user_permissions(user_id, module) VALUES (?, ?)",
            [(user_id, m) for m in modules if m in MODULES],
        )


def allowed_pages(user: dict) -> list[str]:
    """Módulos que o usuário pode abrir (na ordem do menu)."""
    if user["role"] == ROLE_ADMIN:
        return list(MODULES) + list(ADMIN_PAGES)
    granted = get_permissions(user["id"])
    return [m for m in MODULES if m in granted]


def can_access(user: dict | None, page: str) -> bool:
    return bool(user) and page in allowed_pages(user)


def can_edit(user: dict | None) -> bool:
    return bool(user) and user["role"] != ROLE_VIEWER


def is_admin(user: dict | None) -> bool:
    return bool(user) and user["role"] == ROLE_ADMIN


def change_password(user_id: int, new_password: str, *, enforce_policy: bool = True) -> None:
    if enforce_policy:
        errors = password_policy_errors(new_password)
        if errors:
            raise AuthError("Senha fraca: " + ", ".join(errors))
    execute("UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
            (hash_password(new_password), user_id))


def set_temporary_password(user_id: int, temp_password: str) -> None:
    """Define senha provisória e obriga a troca no próximo login."""
    execute("UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
            (hash_password(temp_password), user_id))


def force_password_change(user_id: int, flag: bool = True) -> None:
    execute("UPDATE users SET must_change_password = ? WHERE id = ?", (int(flag), user_id))


def update_user(user_id: int, *, role: str | None = None, active: bool | None = None,
                full_name: str | None = None) -> None:
    conn = connect()
    try:
        if role is not None:
            if role not in ROLES:
                raise AuthError(f"Perfil inválido: {role}")
            conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        if active is not None:
            conn.execute("UPDATE users SET active = ? WHERE id = ?", (int(active), user_id))
        if full_name is not None:
            conn.execute("UPDATE users SET full_name = ? WHERE id = ?", (full_name, user_id))
        conn.commit()
    finally:
        conn.close()


RESTRICTED_MARK = "__restrito__"


def doc_areas(user: dict | None) -> set[str]:
    """Pastas de documentos que o usuário pode ver. Sem restrição cadastrada = todas."""
    if not user:
        return set()
    if user.get("role") == ROLE_ADMIN:
        return set(DOC_AREAS)
    rows = {r["area"] for r in query("SELECT area FROM user_doc_access WHERE user_id = ?", (user["id"],))}
    if RESTRICTED_MARK not in rows:
        return set(DOC_AREAS)
    return rows & set(DOC_AREAS)


def set_doc_areas(user_id: int, areas: list[str] | set[str]) -> None:
    """Grava as pastas liberadas; liberar todas remove a restrição."""
    areas = set(areas) & set(DOC_AREAS)
    with transaction() as conn:
        conn.execute("DELETE FROM user_doc_access WHERE user_id = ?", (user_id,))
        if areas != set(DOC_AREAS):
            conn.executemany("INSERT INTO user_doc_access(user_id, area) VALUES (?, ?)",
                             [(user_id, a) for a in sorted(areas | {RESTRICTED_MARK})])


def can_see_doc(user: dict | None, area: str) -> bool:
    return area in doc_areas(user)
