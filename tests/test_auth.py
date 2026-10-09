import pytest

from erp import auth
from erp.config import ADMIN_PAGES, MODULES


@pytest.fixture
def users(empty_db):
    admin = auth.create_user("admin", "admin123", "Administrador")
    stock = auth.create_user("almoxarife", "campo123", "Almoxarife")
    viewer = auth.create_user("visualizador", "visual123", "Visualizador")
    return admin, stock, viewer


def test_login_three_profiles(users):
    assert auth.authenticate("admin", "admin123")["role"] == "Administrador"
    assert auth.authenticate("ALMOXARIFE ", "campo123")["role"] == "Almoxarife"
    assert auth.authenticate("visualizador", "visual123")["role"] == "Visualizador"
    assert auth.authenticate("admin", "x") is None
    assert "password_hash" not in auth.authenticate("admin", "admin123")


def test_almoxarife_only_stock(users):
    _, stock, _ = users
    user = auth.get_user(stock)
    assert auth.allowed_pages(user) == ["estoque"]
    assert not auth.can_access(user, "fiscal")
    assert not auth.can_access(user, "conexoes")


def test_admin_sees_everything_including_admin_pages(users):
    admin, _, _ = users
    pages = auth.allowed_pages(auth.get_user(admin))
    assert set(MODULES) | set(ADMIN_PAGES) == set(pages)


def test_viewer_is_read_only_and_never_sees_admin_pages(users):
    _, _, viewer = users
    user = auth.get_user(viewer)
    assert not auth.can_edit(user)
    assert "conexoes" not in auth.allowed_pages(user)
    auth.set_permissions(viewer, list(MODULES) + ["conexoes", "usuarios"])  # checkbox não libera páginas de admin
    assert "conexoes" not in auth.allowed_pages(user)


def test_dynamic_permissions(users):
    _, stock, _ = users
    auth.set_permissions(stock, ["estoque", "rdo"])
    assert auth.allowed_pages(auth.get_user(stock)) == ["rdo", "estoque"]


def test_temporary_password_forces_change(users):
    _, _, viewer = users
    auth.set_temporary_password(viewer, "Temp@1234")
    user = auth.authenticate("visualizador", "Temp@1234")
    assert user["must_change_password"] == 1
    with pytest.raises(auth.AuthError):
        auth.change_password(viewer, "fraca")
    auth.change_password(viewer, "NovaSenha2026")
    user = auth.authenticate("visualizador", "NovaSenha2026")
    assert user["must_change_password"] == 0


def test_inactive_user_cannot_login(users):
    _, stock, _ = users
    auth.update_user(stock, active=False)
    assert auth.authenticate("almoxarife", "campo123") is None


def test_duplicate_user(users):
    with pytest.raises(auth.AuthError):
        auth.create_user("admin", "x", "Administrador")
