"""Access grant model: api_key_domains junction table."""
from db import get_db


def grant_domains(
    api_key_id: int,
    domain_ids: list[int],
) -> list[dict]:
    """Upsert access grants for *api_key_id* to each domain in *domain_ids*.

    Returns the full list of domains now granted to the key.
    """
    if domain_ids:
        with get_db() as conn:
            conn.execute_values(
                "INSERT INTO api_key_domains (api_key_id, domain_id)"
                " VALUES %s ON CONFLICT DO NOTHING",
                [(api_key_id, d) for d in domain_ids],
            )
    return list_granted_domains(api_key_id)


def revoke_domain(api_key_id: int, domain_id: int) -> bool:
    """Delete the access grant for *api_key_id* to *domain_id*.

    Returns True if a row was deleted, False if it did not exist.
    """
    with get_db() as conn:
        row = conn.execute(
            "DELETE FROM api_key_domains"
            " WHERE api_key_id = ? AND domain_id = ?"
            " RETURNING api_key_id",
            (api_key_id, domain_id),
        ).fetchone()
    return row is not None


def has_domain_access(api_key_id: int, domain_id: int) -> bool:
    """Return True if *api_key_id* has an access grant for *domain_id*."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM api_key_domains"
            " WHERE api_key_id = ? AND domain_id = ?",
            (api_key_id, domain_id),
        ).fetchone()
    return row is not None


def list_granted_domains(api_key_id: int) -> list[dict]:
    """Return all domains granted to *api_key_id*, ordered by domain id."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT d.* FROM domains d"
            " JOIN api_key_domains akd ON d.id = akd.domain_id"
            " WHERE akd.api_key_id = ?"
            " ORDER BY d.id",
            (api_key_id,),
        ).fetchall()
    return [dict(r) for r in rows]  # type: ignore[return-value]
