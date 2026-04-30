"""Tests for GET /users, GET /users/{id}, and PATCH /users/{id}."""
import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# GET /users
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_users_admin(
    client: AsyncClient,
    admin_caller: str,
    seed_domains: list[str],
) -> None:
    """Admin receives 200 and a list with the expected shape."""
    await client.post("/register", json={
        "username": "list_user_a",
        "email": "list_user_a@example.com",
        "password": "pass",
        "domain_slugs": ["ai_news"],
    })
    resp = await client.get(
        "/users", headers={"x-ocn-caller": admin_caller}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    user = next(u for u in body if u["username"] == "list_user_a")
    assert set(user.keys()) >= {
        "id", "username", "role", "is_active",
        "created_at", "last_login_at", "domains",
    }
    assert "ai_news" in user["domains"]
    assert "password_hash" not in user


@pytest.mark.asyncio
async def test_list_users_non_admin(
    client: AsyncClient,
    user_caller: tuple[str, int],
) -> None:
    """Non-admin receives 403."""
    caller_header, _ = user_caller
    resp = await client.get(
        "/users", headers={"x-ocn-caller": caller_header}
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /users/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_user_by_id(
    client: AsyncClient,
    admin_caller: str,
    seed_domains: list[str],
) -> None:
    """Admin retrieves a specific user by id."""
    reg = await client.post("/register", json={
        "username": "get_by_id_user",
        "email": "get_by_id_user@example.com",
        "password": "pass",
        "domain_slugs": ["robotics"],
    })
    user_id = reg.json()["id"]

    resp = await client.get(
        f"/users/{user_id}",
        headers={"x-ocn-caller": admin_caller},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == user_id
    assert body["username"] == "get_by_id_user"
    assert body["domains"] == ["robotics"]


@pytest.mark.asyncio
async def test_get_user_not_found(
    client: AsyncClient,
    admin_caller: str,
) -> None:
    """Unknown id returns 404."""
    resp = await client.get(
        "/users/999999",
        headers={"x-ocn-caller": admin_caller},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /users/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_is_active(
    client: AsyncClient,
    admin_caller: str,
) -> None:
    """PATCH can deactivate a user."""
    reg = await client.post("/register", json={
        "username": "patch_active_user",
        "email": "patch_active_user@example.com",
        "password": "pass",
        "domain_slugs": [],
    })
    user_id = reg.json()["id"]

    resp = await client.patch(
        f"/users/{user_id}",
        json={"is_active": False},
        headers={"x-ocn-caller": admin_caller},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_patch_role(
    client: AsyncClient,
    admin_caller: str,
) -> None:
    """PATCH can promote a user to admin."""
    reg = await client.post("/register", json={
        "username": "patch_role_user",
        "email": "patch_role_user@example.com",
        "password": "pass",
        "domain_slugs": [],
    })
    user_id = reg.json()["id"]

    resp = await client.patch(
        f"/users/{user_id}",
        json={"role": "admin"},
        headers={"x-ocn-caller": admin_caller},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_patch_domain_slugs(
    client: AsyncClient,
    admin_caller: str,
    seed_domains: list[str],
) -> None:
    """PATCH replaces domain associations entirely."""
    reg = await client.post("/register", json={
        "username": "patch_domains_user",
        "email": "patch_domains_user@example.com",
        "password": "pass",
        "domain_slugs": ["ai_news"],
    })
    user_id = reg.json()["id"]

    resp = await client.patch(
        f"/users/{user_id}",
        json={"domain_slugs": ["robotics"]},
        headers={"x-ocn-caller": admin_caller},
    )
    assert resp.status_code == 200
    assert resp.json()["domains"] == ["robotics"]


@pytest.mark.asyncio
async def test_patch_unknown_domain(
    client: AsyncClient,
    admin_caller: str,
) -> None:
    """Unknown domain slug returns 404."""
    reg = await client.post("/register", json={
        "username": "patch_unknown_dom_user",
        "email": "patch_unknown_dom_user@example.com",
        "password": "pass",
        "domain_slugs": [],
    })
    user_id = reg.json()["id"]

    resp = await client.patch(
        f"/users/{user_id}",
        json={"domain_slugs": ["does_not_exist"]},
        headers={"x-ocn-caller": admin_caller},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_user_not_found(
    client: AsyncClient,
    admin_caller: str,
) -> None:
    """PATCH on unknown id returns 404."""
    resp = await client.patch(
        "/users/999999",
        json={"is_active": False},
        headers={"x-ocn-caller": admin_caller},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_deactivated_user_cannot_login(
    client: AsyncClient,
    admin_caller: str,
) -> None:
    """Deactivating a user via PATCH prevents them from logging in."""
    reg = await client.post("/register", json={
        "username": "deactivate_login_user",
        "email": "deactivate_login_user@example.com",
        "password": "pass",
        "domain_slugs": [],
    })
    user_id = reg.json()["id"]

    login_ok = await client.post("/login", json={
        "username": "deactivate_login_user",
        "password": "pass",
    })
    assert login_ok.status_code == 200

    await client.patch(
        f"/users/{user_id}",
        json={"is_active": False},
        headers={"x-ocn-caller": admin_caller},
    )

    resp = await client.post("/login", json={
        "username": "deactivate_login_user",
        "password": "pass",
    })
    assert resp.status_code == 403
