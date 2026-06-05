"""Environment configuration for research-universe."""
import os

POSTGRES_HOST: str = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT: int = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_DB: str = os.environ.get("POSTGRES_DB", "research-universe")
POSTGRES_USER: str = os.environ.get("POSTGRES_USER", "research-universe")
POSTGRES_PASSWORD: str = os.environ.get("POSTGRES_PASSWORD", "")

OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL: str = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4-6")

# Comma-separated list of allowed CORS origins (CloudFront URL in production)
CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]

PORT: int = int(os.environ.get("PORT", "8007"))

# When deployed behind the ALB, all requests arrive with /universe prefix.
# Set API_PREFIX=/universe in production; leave empty for local dev.
API_PREFIX: str = os.environ.get("API_PREFIX", "").rstrip("/")
