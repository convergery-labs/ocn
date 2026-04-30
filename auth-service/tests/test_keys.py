"""Tests for /keys endpoints."""


async def test_get_keys_with_admin_returns_200(
    client, admin_caller
) -> None:
    """GET /keys with a valid admin caller header returns 200 and a list."""
    resp = await client.get(
        "/keys",
        headers={"x-ocn-caller": admin_caller},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_get_keys_response_excludes_key_hash(
    client, admin_caller
) -> None:
    """GET /keys must not expose key_hash in any row."""
    resp = await client.get(
        "/keys",
        headers={"x-ocn-caller": admin_caller},
    )
    for row in resp.json():
        assert "key_hash" not in row


async def test_get_keys_with_user_returns_403(
    client, user_caller
) -> None:
    """GET /keys with a user-role caller must return 403."""
    key, _ = user_caller
    resp = await client.get(
        "/keys",
        headers={"x-ocn-caller": key},
    )
    assert resp.status_code == 403


async def test_get_keys_no_caller_returns_401(client) -> None:
    """GET /keys with no x-ocn-caller header returns 401."""
    resp = await client.get("/keys")
    assert resp.status_code == 401


async def test_post_key_returns_201_with_plaintext(
    client, admin_caller
) -> None:
    """POST /keys returns 201 and includes the plaintext key once."""
    resp = await client.post(
        "/keys",
        json={"label": "integration-test", "role": "user"},
        headers={"x-ocn-caller": admin_caller},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "key" in body
    assert body["key"].startswith("csec_")
    assert len(body["key"]) == len("csec_") + 64
    assert body["role"] == "user"
    assert body["label"] == "integration-test"


async def test_post_key_with_user_returns_403(
    client, user_caller
) -> None:
    """POST /keys with a user-role caller must return 403."""
    key, _ = user_caller
    resp = await client.post(
        "/keys",
        json={"label": "x", "role": "user"},
        headers={"x-ocn-caller": key},
    )
    assert resp.status_code == 403


async def test_post_key_invalid_role_returns_422(
    client, admin_caller
) -> None:
    """POST /keys with an invalid role value must return 422."""
    resp = await client.post(
        "/keys",
        json={"label": "x", "role": "superuser"},
        headers={"x-ocn-caller": admin_caller},
    )
    assert resp.status_code == 422
