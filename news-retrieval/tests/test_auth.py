"""Tests for authentication and authorisation enforcement."""


async def test_missing_auth_header_returns_422(client) -> None:
    """Absent Authorization header returns 422 (required field)."""
    resp = await client.get("/domains")
    assert resp.status_code == 422


async def test_unknown_bearer_token_returns_401(client) -> None:
    """An unrecognised API key must return 401."""
    resp = await client.get(
        "/domains",
        headers={"Authorization": "Bearer cnews_unknown_key"},
    )
    assert resp.status_code == 401


async def test_malformed_auth_scheme_returns_401(client) -> None:
    """A non-Bearer Authorization value must return 401."""
    resp = await client.get(
        "/domains",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert resp.status_code == 401


async def test_user_key_on_admin_endpoint_returns_403(
    client, user_key
) -> None:
    """A user-role key must receive 403 on admin-only endpoints."""
    key, _ = user_key
    resp = await client.post(
        "/api-keys",
        json={"label": "x", "role": "user"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 403
