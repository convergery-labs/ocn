"""Normalised document schema shared across all historical adapters."""
from dataclasses import dataclass, field
from datetime import date


@dataclass
class HistoricalDocument:
    """A document fetched from any historical source adapter."""

    url: str
    title: str
    body: str
    source_type: str        # "news" | "research"
    published_date: date
    source_adapter: str     # "gdelt" | "arxiv"
    metadata: dict = field(default_factory=dict)
