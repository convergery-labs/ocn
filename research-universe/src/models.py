from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DiscoveryRow:
    # Identity — always present
    run_id: str
    source: str
    company_name: str

    # From source — present for Alpha Vantage, may be None for others
    ticker: str | None = None
    exchange: str | None = None
    country_market: str | None = None
    source_description: str | None = None
    seed_url: str | None = None

    # Filled by enrich step
    official_url: str | None = None
    page_summary: str | None = None

    # Set by enrich step
    url_status: str = "missing"       # grounded | weak | missing | invalid
    summary_status: str = "blank"     # grounded | weak | blank

    # Set by dedupe check in stage step
    duplicate_status: str = "new"     # new | duplicate | possible_duplicate
    possible_duplicate: str | None = None
    review_note: str | None = None

    # Overall row status — progresses through the pipeline
    row_status: str = "staged"        # staged → pending | blocked → classified_add | classified_skip | error

    # Filled by classify step
    category: str | None = None
    subcategory: str | None = None
    company_type: str | None = None
    universe_type: str | None = None
    classifier_reason: str | None = None

    date_added: str = ""
    source_urls: list[str] = field(default_factory=list)
