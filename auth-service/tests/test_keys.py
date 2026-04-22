"""Tests for /keys endpoints."""


async def test_get_keys_with_admin_returns_200(client, admin_key) -> None:
    """GET /keys with a valid admin key returns 200 and a list."""
    resp = await client.get(
        "/keys",
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_get_keys_response_excludes_key_hash(
    client, admin_key
) -> None:
    """GET /keys must not expose key_hash in any row."""
    resp = await client.get(
        "/keys",
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    for row in resp.json():
        assert "key_hash" not in row


async def test_get_keys_with_user_returns_403(client, user_key) -> None:
    """GET /keys with a user-role key must return 403."""
    key, _ = user_key
    resp = await client.get(
        "/keys",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 403


async def test_get_keys_no_auth_returns_422(client) -> None:
    """GET /keys with no Authorization header returns 422."""
    resp = await client.get("/keys")
    assert resp.status_code == 422


async def test_post_key_returns_201_with_plaintext(
    client, admin_key
) -> None:
    """POST /keys returns 201 and includes the plaintext key once."""
    resp = await client.post(
        "/keys",
        json={"label": "integration-test", "role": "user"},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "key" in body
    assert body["key"].startswith("csec_")
    assert len(body["key"]) == len("csec_") + 64
    assert body["role"] == "user"
    assert body["label"] == "integration-test"


async def test_post_key_with_user_returns_403(client, user_key) -> None:
    """POST /keys with a user-role key must return 403."""
    key, _ = user_key
    resp = await client.post(
        "/keys",
        json={"label": "x", "role": "user"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 403


async def test_post_key_invalid_role_returns_422(
    client, admin_key
) -> None:
    """POST /keys with an invalid role value must return 422."""
    resp = await client.post(
        "/keys",
        json={"label": "x", "role": "superuser"},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 422
