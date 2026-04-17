"""Domain controller."""
from typing import Optional

from pydantic import BaseModel

from models import domains as domain_model


class DomainIn(BaseModel):
    """Request body for POST /domains."""

    name: str
    slug: str
    description: Optional[str] = None


def get_all() -> list[dict]:
    """Return all domains."""
    return domain_model.list_domains()


def create(body: DomainIn) -> dict:
    """Create a domain and return it.

    Raises:
        DuplicateError: if name or slug already exists.
    """
    domain_id = domain_model.insert_domain(
        body.name, body.slug, body.description
    )
    return domain_model.get_domain_by_id(domain_id)
