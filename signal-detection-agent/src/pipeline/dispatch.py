"""Route an item to its source-specific classifier by source_type.

source_type is always known upfront (it comes from which fetch pipeline
produced the item), never inferred - this is a lookup, not a decision, so a
plain registry is enough. Add a new source_type by adding one entry below;
no other file needs to change to add a new domain.
"""
from __future__ import annotations

from typing import Any, Callable

from pipeline.filing_classifier import classify_filing
from pipeline.geopolitical_classifier import classify_geopolitical_article

ClassifierFn = Callable[..., dict[str, Any]]

# Each entry is the classifier function for that source_type. Signatures vary
# by domain (classify_article_two_stage takes an article + context-gathering
# callbacks; classify_filing takes a filing + fetched text; classify_geopolitical_article
# takes an article + system_prompt, single-pass) - callers must still pass the
# right kwargs for whichever classifier they're dispatching to. This registry
# only answers "which function", not "which arguments".
_CLASSIFIERS: dict[str, ClassifierFn] = {
    "sec_filing": classify_filing,
    "geopolitical_news": classify_geopolitical_article,
}


def register_classifier(source_type: str, fn: ClassifierFn) -> None:
    """Register a classifier for a new source_type. Call once at import time
    from the module that defines it (mirrors how classify_filing is wired
    below) - keeps each domain's classifier module self-contained rather than
    editing this file every time a new source is added.
    """
    _CLASSIFIERS[source_type] = fn


def get_classifier(source_type: str) -> ClassifierFn:
    """Return the classifier function for source_type, or raise if unknown."""
    try:
        return _CLASSIFIERS[source_type]
    except KeyError:
        raise ValueError(
            f"No classifier registered for source_type={source_type!r}. "
            f"Known: {sorted(_CLASSIFIERS)}"
        ) from None


def known_source_types() -> list[str]:
    return sorted(_CLASSIFIERS)
