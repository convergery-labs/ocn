"""Configuration: categories, recipients, and environment variables."""
import os

CATEGORIES: list[str] = [
    "Raw Materials & Critical Minerals",
    "Energy & Grid Infrastructure",
    "Nuclear & Advanced Energy",
    "Semiconductor Manufacturing",
    "Compute Hardware & Edge Systems",
    "Networking, Optical & Interconnect",
    "Data Centers & Physical Infrastructure",
    "Telecom & Connectivity",
    "Cloud & Compute Platforms",
    "AI Software Infrastructure",
    "AI Data Infrastructure",
    "AI Models & Intelligence Layer",
    "Robotics & Physical AI",
    "Quantum Computing & Sensing",
    "Life Sciences & Healthcare AI",
    "Defense, Aerospace & Sovereign AI",
    "Financial Infrastructure & AI Capital",
    "Water & Resource Infrastructure",
    "Applications & Digital Economy",
]

EMAIL_RECIPIENTS: list[str] = [
    "ayushi.shah@opengrowth.com",
    "wasikul.islam@cern.ch",
    "kajal@foliumlabs.net",
]

if _test_email := os.environ.get("DIGEST_TEST_EMAIL"):
    EMAIL_RECIPIENTS = [_test_email]

SIGNAL_AGENT_URL: str = os.environ.get(
    "SIGNAL_AGENT_URL", "http://localhost:8003"
)

SIGNAL_HERALD_URL: str = os.environ.get(
    "SIGNAL_HERALD_URL", "http://localhost:8006"
)

SIGNAL_CALLER_SUB: int = int(os.environ.get("SIGNAL_CALLER_SUB", "1"))

OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL: str = os.environ.get(
    "OPENROUTER_MODEL", "openai/gpt-4o-mini"
)

SMTP_HOST: str = os.environ.get("SMTP_HOST", "")
SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER: str = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD: str = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM: str = os.environ.get("SMTP_FROM", "")

POLL_INTERVAL_SECONDS: int = 30
POLL_MAX_ATTEMPTS: int = 120
