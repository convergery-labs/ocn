"""Hardcoded domain configuration."""
from typing import TypedDict


class DomainConfig(TypedDict):
    """Configuration for a single domain."""

    slug: str
    description: str
    verticals: list[str]


DOMAINS: dict[str, DomainConfig] = {
    "ai_news": {
        "slug": "ai_news",
        "description": "AI and machine learning industry news",
        "verticals": [
            "foundation_models",
            "ai_applications",
            "ai_regulation",
            "robotics",
            "ai_research",
        ],
    },
    "smart_money": {
        "slug": "smart_money",
        "description": (
            "Venture capital, private equity, and institutional "
            "investment news"
        ),
        "verticals": [
            "fundraising",
            "acquisitions",
            "ipo",
            "portfolio_companies",
            "market_trends",
        ],
    },
}
