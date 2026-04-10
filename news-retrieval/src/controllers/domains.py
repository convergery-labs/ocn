"""Domain controller — orchestrates domain and taxonomy creation."""
from typing import Optional

from pydantic import BaseModel, Field

from models.atomic import atomic
from models import domains as domain_model
from models import taxonomies as taxonomy_model


class TaxonomyCategoryIn(BaseModel):
    """A single taxonomy category for inline domain creation."""

    category: str
    position: Optional[int] = Field(
        default=None,
        description=(
            "Display order. Auto-assigned (1, 2, …) when omitted."
        ),
    )


class DomainIn(BaseModel):
    """Request body for POST /domains."""

    name: str
    slug: str
    description: Optional[str] = None
    taxonomy: list[TaxonomyCategoryIn] = Field(
        default_factory=list,
        description="Taxonomy categories to create with the domain.",
    )


def get_all() -> list[dict]:
    """Return all domains."""
    return domain_model.list_domains()


def create(body: DomainIn) -> dict:
    """Create a domain and its taxonomy in a single transaction.

    Returns the created domain dict with a ``taxonomy`` key containing
    the list of created category rows.

    Raises:
        sqlite3.IntegrityError: if name or slug already exists, or a
            category is duplicated within the taxonomy list.
    """
    with atomic():
        domain_id = domain_model.insert_domain(
            body.name, body.slug, body.description
        )
        for i, entry in enumerate(body.taxonomy, start=1):
            taxonomy_model.insert_taxonomy(
                domain_id=domain_id,
                category=entry.category,
                position=(
                    entry.position
                    if entry.position is not None
                    else i
                ),
            )
        domain = domain_model.get_domain_by_id(domain_id)
        taxonomy = taxonomy_model.list_by_domain_id(domain_id)

    return {**domain, "taxonomy": taxonomy}
