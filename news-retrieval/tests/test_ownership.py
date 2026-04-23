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


async def test_multi_key_access_to_same_domain(
    client, admin_key, user_key, other_user_key, daily_frequency_id
) -> None:
    """Two user keys granted access to the same domain can both POST sources."""
    user_k, _ = user_key
    other_k, _ = other_user_key

    # Create a domain as user_key (auto-grants user_key access)
    resp = await client.post(
        "/domains",
        json={"name": "Shared Domain", "slug": "shared-domain"},
        headers={"Authorization": f"Bearer {user_k}"},
    )
    assert resp.status_code == 201
    domain_id = resp.json()["id"]

    # Admin grants other_user_key access to the same domain
    resp = await client.post(
        f"/api-keys/{other_user_key[1]}/domains",
        json={"domain_ids": [domain_id]},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 200

    # Both keys can POST sources
    for key, url in [
        (user_k, "http://shared-user.example.com/feed.xml"),
        (other_k, "http://shared-other.example.com/feed.xml"),
    ]:
        resp = await client.post(
            "/sources",
            json={
                "url": url,
                "domain_id": domain_id,
                "frequency_id": daily_frequency_id,
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 201


async def test_revoked_access_returns_403(
    client, admin_key, user_key, other_user_key, daily_frequency_id
) -> None:
    """After revoking a grant, the key gets 403 on POST /sources."""
    user_k, _ = user_key
    other_k, other_id = other_user_key

    # Create a domain as user_key
    resp = await client.post(
        "/domains",
        json={"name": "Revoke Domain", "slug": "revoke-domain"},
        headers={"Authorization": f"Bearer {user_k}"},
    )
    assert resp.status_code == 201
    domain_id = resp.json()["id"]

    # Grant other_user_key access
    await client.post(
        f"/api-keys/{other_id}/domains",
        json={"domain_ids": [domain_id]},
        headers={"Authorization": f"Bearer {admin_key}"},
    )

    # other_user_key can POST source
    resp = await client.post(
        "/sources",
        json={
            "url": "http://revoke-before.example.com/feed.xml",
            "domain_id": domain_id,
            "frequency_id": daily_frequency_id,
        },
        headers={"Authorization": f"Bearer {other_k}"},
    )
    assert resp.status_code == 201

    # Revoke other_user_key's access
    resp = await client.delete(
        f"/api-keys/{other_id}/domains/{domain_id}",
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 204

    # other_user_key is now denied
    resp = await client.post(
        "/sources",
        json={
            "url": "http://revoke-after.example.com/feed.xml",
            "domain_id": domain_id,
            "frequency_id": daily_frequency_id,
        },
        headers={"Authorization": f"Bearer {other_k}"},
    )
    assert resp.status_code == 403


async def test_admin_bypass_unaffected(
    client, admin_key, user_key, daily_frequency_id
) -> None:
    """Admin can POST sources to any domain regardless of grants."""
    user_k, _ = user_key

    # Create a domain as user_key (only user_key has a grant)
    resp = await client.post(
        "/domains",
        json={"name": "Admin Bypass Domain", "slug": "admin-bypass"},
        headers={"Authorization": f"Bearer {user_k}"},
    )
    assert resp.status_code == 201
    domain_id = resp.json()["id"]

    # Admin can POST source without an explicit grant
    resp = await client.post(
        "/sources",
        json={
            "url": "http://admin-bypass.example.com/feed.xml",
            "domain_id": domain_id,
            "frequency_id": daily_frequency_id,
        },
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 201


async def test_grant_domains_endpoint_returns_domain_list(
    client, admin_key, user_key, other_user_key
) -> None:
    """POST /api-keys/{id}/domains returns the updated domain list."""
    user_k, _ = user_key
    _, other_id = other_user_key

    # Create a domain as user_key
    resp = await client.post(
        "/domains",
        json={"name": "Grant Test Domain", "slug": "grant-test"},
        headers={"Authorization": f"Bearer {user_k}"},
    )
    assert resp.status_code == 201
    domain_id = resp.json()["id"]

    # Grant other_user_key access
    resp = await client.post(
        f"/api-keys/{other_id}/domains",
        json={"domain_ids": [domain_id]},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 200
    granted_ids = [d["id"] for d in resp.json()]
    assert domain_id in granted_ids


async def test_revoke_domain_endpoint_404_on_missing_grant(
    client, admin_key, other_user_key
) -> None:
    """DELETE /api-keys/{id}/domains/{did} returns 404 if grant absent."""
    _, other_id = other_user_key
    resp = await client.delete(
        f"/api-keys/{other_id}/domains/99999",
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 404


