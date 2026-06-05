"""spaCy NER pipeline for concept extraction.

Loads en_core_web_lg once at import time and maps extracted entities /
noun chunks to concept taxonomy slugs using taxonomy_mappings.json.
"""
import json
import logging
import os
import re
from pathlib import Path

import spacy

logger = logging.getLogger(__name__)

_MAPPINGS_PATH = Path(__file__).parent.parent / "taxonomy_mappings.json"

# Characters fed to spaCy per article - caps latency without losing coverage.
_MAX_TEXT_CHARS = 50_000


def _load_mappings() -> dict[str, str]:
    """Load keyword → concept-slug mappings from taxonomy_mappings.json."""
    with open(_MAPPINGS_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _load_model() -> spacy.language.Language:
    """Load the en_core_web_lg spaCy model."""
    return spacy.load("en_core_web_lg")


try:
    _NLP = _load_model()
    _MAPPINGS: dict[str, str] = _load_mappings()
except Exception:  # pragma: no cover
    logger.exception("Failed to load NER pipeline - concept extraction disabled")
    _NLP = None  # type: ignore[assignment]
    _MAPPINGS = {}


def extract_concepts(text: str) -> list[str]:
    """Return deduplicated concept slugs present in text.

    Uses spaCy named-entity recognition and noun chunks to surface
    candidate terms, then matches them against taxonomy_mappings.json
    via case-insensitive substring lookup.

    Returns an empty list if text is empty, no concepts are matched,
    or the pipeline failed to load - never raises.
    """
    if not _NLP or not text:
        return []
    try:
        doc = _NLP(text[:_MAX_TEXT_CHARS])
        tokens: set[str] = set()
        for ent in doc.ents:
            tokens.add(ent.text.lower())
        for chunk in doc.noun_chunks:
            tokens.add(chunk.text.lower())

        matched: set[str] = set()
        for pattern, slug in _MAPPINGS.items():
            regex = re.compile(
                r"\b" + re.escape(pattern) + r"\b"
            )
            for token in tokens:
                if regex.search(token):
                    matched.add(slug)
                    break

        return sorted(matched)
    except Exception:
        logger.warning(
            "NER concept extraction failed for text preview %.80r",
            text,
            exc_info=True,
        )
        return []
