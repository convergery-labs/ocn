"""Domain controller."""
from typing import Optional

from pydantic import BaseModel

from models import domains as domain_model
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


def get_all() -> list[dict]:
    """Return all domains."""
    return domain_model.list_domains()


def create(body: DomainIn, caller: ApiKeyRow) -> dict:
    """Create a domain owned by *caller* and return it.

    Raises:
        DuplicateError: if name or slug already exists.
    """
    domain_id = domain_model.insert_domain(
        body.name, body.slug, body.description, created_by=caller["id"]
    )
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
    """Raise ValueError if caller is neither owner nor admin."""
    if caller["role"] == "admin":
        return
    if domain.get("created_by") == caller["id"]:
        return
    raise PermissionError("You do not own this domain.")
