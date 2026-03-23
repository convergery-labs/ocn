"""AI news domain: taxonomy and agent instance."""
from agent import NewsAgent
from feeds import AI_NEWS_FEEDS, AI_NEWS_FEEDS_WEEKLY

TAXONOMY = [
    "AI Agents & Automation",
    "AI Models & Research",
    "AI Hardware & Semiconductors",
    "Data Center Infrastructure",
    "Energy & Sustainability",
    "Robotics & Physical AI",
    "Edge & Local AI",
    "Enterprise AI & Productivity",
    "AI Security & Privacy",
    "AI Policy & Governance",
    "AI Funding & Startups",
    "AI in Science & Society",
]

agent = NewsAgent(
    name="AI",
    feeds=AI_NEWS_FEEDS,
    taxonomy=TAXONOMY,
    fetch_tool_name="fetch_ai_news",
    weekly_feeds=AI_NEWS_FEEDS_WEEKLY,
)
