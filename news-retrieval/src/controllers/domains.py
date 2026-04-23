"""Domain controller."""
from typing import Optional

from pydantic import BaseModel

from models import domains as domain_model
from models.api_key_domains import grant_domains, has_domain_access
from models.api_keys import ApiKeyRow


class DomainIn(BaseModel):
    """Request body for POST /domains."""

    name: str
    slug: str
    description: Optional[str] = None


class DomainPatch(BaseModel):
    """Request body for PATCH /domains/{id}."""

    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None


def get_all(caller: ApiKeyRow) -> list[dict]:
    """Return domains visible to *caller*.

    Admins see all domains; regular callers see only their own and
    null-owner (legacy) domains.
    """
    if caller["role"] == "admin":
        return domain_model.list_domains()
    return domain_model.list_domains(caller_id=caller["id"])


def create(body: DomainIn, caller: ApiKeyRow) -> dict:
    """Create a domain owned by *caller*, grant access, and return it.

    Raises:
        DuplicateError: if name or slug already exists.
    """
    domain_id = domain_model.insert_domain(
        body.name, body.slug, body.description,
        created_by=caller["id"],
    )
    grant_domains(caller["id"], [domain_id])
    return domain_model.get_domain_by_id(domain_id)


def update(
    domain_id: int,
    body: DomainPatch,
    caller: ApiKeyRow,
) -> dict:
    """Update a domain if *caller* owns it or is an admin.

    Raises:
        HTTPException 403: if caller does not own the domain and is
            not an admin (raised by the route layer after this check).
        ValueError: if the domain does not exist.
        DuplicateError: if the new name or slug conflicts.
    """
    domain = domain_model.get_domain_by_id(domain_id)
    _assert_owner_or_admin(domain, caller)
    return domain_model.update_domain(
        domain_id, body.name, body.slug, body.description
    )


def _assert_owner_or_admin(
    domain: dict,
    caller: ApiKeyRow,
) -> None:
    """Raise PermissionError if caller lacks access and is not admin."""
    if caller["role"] == "admin":
        return
    if domain.get("created_by") is None:
        return
    if not has_domain_access(caller["id"], domain["id"]):
        raise PermissionError("You do not own this domain.")
