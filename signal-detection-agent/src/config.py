"""Environment-variable configuration for signal-detection-agent."""
import os
from pathlib import Path

OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL: str = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL: str = os.environ.get("SIGNAL_DETECTION_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-4.1"
OPENAI_TIMEOUT: int = int(os.environ.get("OPENAI_TIMEOUT", "90"))
OPENAI_MAX_ATTEMPTS: int = int(os.environ.get("OPENAI_MAX_ATTEMPTS", "2"))
CLASSIFY_CONCURRENCY: int = int(os.environ.get("CLASSIFY_CONCURRENCY", "8"))

NEWS_RETRIEVAL_URL: str = os.environ.get("NEWS_RETRIEVAL_URL", "http://news-retrieval:8000")
NEWS_RETRIEVAL_SERVICE_CALLER: str = os.environ.get(
    "NEWS_RETRIEVAL_SERVICE_CALLER",
    "eyJzdWIiOiAwLCAicm9sZSI6ICJhZG1pbiIsICJkb21haW5zIjogW119",
)
PIPELINE_POLL_TIMEOUT_SECS: int = int(os.environ.get("PIPELINE_POLL_TIMEOUT_SECS", "600"))

PROMPTS_DIR: Path = Path(__file__).parent.parent / "prompts"
DEFAULT_PROMPT: Path = PROMPTS_DIR / "ai_universe_signal_classifier_v1.txt"
