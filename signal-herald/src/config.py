"""Configuration: categories, recipients, and environment variables."""
import os

CATEGORIES: list[str] = [
    "Minerals & Raw Materials",
    "Energy",
    "Semiconductor Manufacturing",
    "Computer Hardware",
    "Thermal & Cooling",
    "Data Center Infrastructure",
    "Cloud & Compute Market",
    "Software / Infrastructure",
    "AI Data",
    "AI Models",
    "Applications & Economy",
]

EMAIL_RECIPIENTS: list[str] = [
    "gunjan@opengrowth.com",
    "karan@nasiko.com",
    "ayushi.shah@opengrowth.com",
    "aditya.jaiswal@opengrowth.com",
    "wasikul.islam@cern.ch",
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
