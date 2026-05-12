"""Load the Research Universe tab and build a dedup registry."""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from sheets.client import SheetsClient

_TAB = "Research Universe"
_PRIVATE_TICKER = "Private / No public ticker"


def normalize_name(name: str) -> str:
    """Lowercase and strip punctuation, keeping spaces."""
    return re.sub(r"[^\w\s]", "", name.lower()).strip()


def root_domain(url: str) -> str | None:
    """Extract root domain, stripping www. prefix. Returns None if unparseable."""
    try:
        netloc = urllib.parse.urlparse(url).netloc
        return netloc.removeprefix("www.") or None
    except Exception:
        return None


@dataclass
class DedupeRegistry:
    by_ticker: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_name: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Populated incrementally by the stage controller as official URLs are discovered;
    # the Research Universe tab has no URL column so this starts empty.
    by_domain: dict[str, dict[str, Any]] = field(default_factory=dict)
    all_names: list[str] = field(default_factory=list)


def load(client: SheetsClient) -> DedupeRegistry:
    """Read Research Universe tab and return a populated DedupeRegistry."""
    rows = client.read_tab(_TAB)
    registry = DedupeRegistry()

    for row in rows:
        company = row.get("Company", "").strip()
        ticker = row.get("Ticker / Symbol / Identifier", "").strip()

        if not company:
            continue

        if ticker and ticker != _PRIVATE_TICKER:
            registry.by_ticker[ticker.upper()] = row

        norm = normalize_name(company)
        if norm:
            registry.by_name[norm] = row

        # Category may be a dual entry ("A; B") — stored as-is; no splitting needed here.
        registry.all_names.append(company)

    return registry
