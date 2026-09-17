"""Stage C deterministic overrides - applied after Layer 2's model call,
before Layer 3's ticker expansion. Force-add categories for a few
situations judged too certain to leave to the model, per the spec.

Category names below are the real values from ALLOWED_CATEGORIES
(pipeline/categories.py) - the spec's original examples used invented
snake_case slugs (semiconductor_manufacturing, etc.) that don't correspond
to anything in research-universe's real taxonomy; corrected here to the
real display names.

Overrides only ever ADD categories to what Layer 2 already returned -
never remove or replace the model's own picks.
"""
from __future__ import annotations

_TAIWAN_CONFLICT_CATEGORIES: list[str] = [
    "Semiconductor Manufacturing",
    "Compute Hardware & Edge Systems",
    "Networking, Optical & Interconnect",
    "Cloud & Compute Platforms",
]

_TAIWAN_ACTOR_TERMS = frozenset({"taiwan", "taiwan strait"})


def apply_overrides(
    *,
    channel: str | None,
    actors: list[str] | None,
    assets: list[str] | None,
    impacted_categories: list[str] | None,
) -> list[str]:
    """Return the final impacted_categories list: Layer 2's own picks plus
    any categories a matching override rule forces in, deduplicated,
    order-preserving (Layer 2's picks first, then any newly-forced ones).
    """
    result = list(impacted_categories or [])
    result_set = set(result)

    actor_terms = {a.strip().lower() for a in (actors or [])}

    # Rule 1: Taiwan/Taiwan Strait conflict -> always force the 4 categories
    # most directly exposed to a Taiwan Strait military scenario.
    if channel == "conflict" and actor_terms & _TAIWAN_ACTOR_TERMS:
        for category in _TAIWAN_CONFLICT_CATEGORIES:
            if category not in result_set:
                result.append(category)
                result_set.add(category)

    # Rule 2: US-China trade/sanctions action touching semis -> at least
    # Semiconductor Manufacturing, even if Layer 2 missed it.
    if (
        channel in ("trade", "sanctions")
        and "us" in actor_terms
        and "china" in actor_terms
        and assets
        and "semis" in assets
    ):
        if "Semiconductor Manufacturing" not in result_set:
            result.append("Semiconductor Manufacturing")
            result_set.add("Semiconductor Manufacturing")

    return result
