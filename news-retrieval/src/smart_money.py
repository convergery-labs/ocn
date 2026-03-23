"""Smart Money domain: taxonomy and agent instance."""
from agent import NewsAgent
from feeds import SMART_MONEY_FEEDS

TAXONOMY = [
    "Agentic Payments & AI Wallets",
    "Machine Economy & AI-to-AI Transactions",
    "Stablecoins & On-Chain Settlement",
    "Cross-Border Payments & Real-Time Settlement",
    "Embedded Finance & API Banking",
    "AI Fraud Detection & Compliance",
    "Treasury Automation & Enterprise Finance",
]

agent = NewsAgent(
    name="Smart Money",
    feeds=SMART_MONEY_FEEDS,
    taxonomy=TAXONOMY,
    fetch_tool_name="fetch_smart_money_news",
)
