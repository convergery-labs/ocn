"""Tests for multi-tenant ownership enforcement."""


async def test_post_source_by_non_owner_returns_403(
    client, other_user_key, user_domain, daily_frequency_id
) -> None:
    """Adding a source to another user's domain must return 403."""
    key, _ = other_user_key
    resp = await client.post(
        "/sources",
        json={
            "url": "http://non-owner.example.com/feed.xml",
            "domain_id": user_domain,
            "frequency_id": daily_frequency_id,
        },
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 403


async def test_post_source_by_owner_returns_201(
    client, user_key, user_domain, daily_frequency_id
) -> None:
    """Domain owner can add a source to their domain."""
    key, _ = user_key
    resp = await client.post(
        "/sources",
        json={
            "url": "http://owner.example.com/feed.xml",
            "domain_id": user_domain,
            "frequency_id": daily_frequency_id,
        },
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 201


async def test_patch_domain_by_non_owner_returns_403(
    client, other_user_key, user_domain
) -> None:
    """PATCH /domains/{id} by a non-owner must return 403."""
    key, _ = other_user_key
    resp = await client.patch(
        f"/domains/{user_domain}",
        json={"description": "unauthorized update"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 403


async def test_null_owner_domains_visible_to_all_users(
    client, user_key
) -> None:
    """Seeded null-owner domains appear in GET /domains for any user."""
    key, _ = user_key
    resp = await client.get(
        "/domains",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 200
    slugs = {d["slug"] for d in resp.json()}
    assert "ai_news" in slugs
    assert "smart_money" in slugs
