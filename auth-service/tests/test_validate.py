"""Tests for POST /validate."""


async def test_validate_admin_key_returns_200(client, admin_key) -> None:
    """A valid admin key returns 200 with correct metadata."""
    resp = await client.post(
        "/validate",
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["role"] == "admin"
    assert isinstance(body["key_id"], int)


async def test_validate_user_key_returns_200(client, user_key) -> None:
    """A valid user key returns 200 with correct metadata."""
    key, key_id = user_key
    resp = await client.post(
        "/validate",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["role"] == "user"
    assert body["key_id"] == key_id


async def test_validate_unknown_key_returns_401(client) -> None:
    """An unrecognised key must return 401."""
    resp = await client.post(
        "/validate",
        headers={"Authorization": "Bearer csec_" + "0" * 64},
    )
    assert resp.status_code == 401


async def test_validate_missing_header_returns_401(client) -> None:
    """A missing Authorization header must return 401."""
    resp = await client.post("/validate")
    assert resp.status_code == 401


async def test_validate_malformed_scheme_returns_401(client) -> None:
    """A non-Bearer Authorization value must return 401."""
    resp = await client.post(
        "/validate",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert resp.status_code == 401
