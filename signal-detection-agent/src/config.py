"""Environment-variable configuration for signal-detection-agent."""
import os
from pathlib import Path

OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL: str = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL: str = os.environ.get("SIGNAL_DETECTION_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-4.1"
OPENAI_MODEL_V2: str = os.environ.get("SIGNAL_DETECTION_MODEL_V2") or OPENAI_MODEL
SEC_FILING_MODEL: str = os.environ.get("SEC_FILING_MODEL") or OPENAI_MODEL
OPENAI_TIMEOUT: int = int(os.environ.get("OPENAI_TIMEOUT", "90"))
OPENAI_MAX_ATTEMPTS: int = int(os.environ.get("OPENAI_MAX_ATTEMPTS", "2"))
CLASSIFY_CONCURRENCY: int = int(os.environ.get("CLASSIFY_CONCURRENCY", "8"))

NEWS_RETRIEVAL_URL: str = os.environ.get("NEWS_RETRIEVAL_URL", "http://news-retrieval:8000")
NEWS_RETRIEVAL_SERVICE_CALLER: str = os.environ.get(
    "NEWS_RETRIEVAL_SERVICE_CALLER",
    "eyJzdWIiOiAwLCAicm9sZSI6ICJhZG1pbiIsICJkb21haW5zIjogW119",
)
PIPELINE_POLL_TIMEOUT_SECS: int = int(os.environ.get("PIPELINE_POLL_TIMEOUT_SECS", "600"))

WEB_SEARCH_PROVIDER: str = os.environ.get("WEB_SEARCH_PROVIDER", "duckduckgo")
WEB_SEARCH_API_KEY: str | None = os.environ.get("WEB_SEARCH_API_KEY") or None

FILING_CLASSIFY_CONCURRENCY: int = int(os.environ.get("FILING_CLASSIFY_CONCURRENCY", "5"))
SEC_FILING_DOMAIN: str = os.environ.get("SEC_FILING_DOMAIN", "sec_filing")

PROMPTS_DIR: Path = Path(__file__).parent.parent / "prompts"
DEFAULT_PROMPT: Path = PROMPTS_DIR / "ai_universe_signal_classifier_v1.txt"
DEFAULT_PROMPT_V2: Path = PROMPTS_DIR / "ai_universe_signal_classifier_v2_refine.txt"

TAIWAN_SIGNAL_DOMAIN: str = os.environ.get("TAIWAN_SIGNAL_DOMAIN", "taiwan_market_signal")
KOREA_SIGNAL_DOMAIN: str = os.environ.get("KOREA_SIGNAL_DOMAIN", "korea_market_signal")
NEWS_DOMAIN: str = os.environ.get("NEWS_DOMAIN", "ai_news")
GEOPOLITICAL_SIGNAL_DOMAIN: str = os.environ.get("GEOPOLITICAL_SIGNAL_DOMAIN", "geopolitical_news")
# Stage B is a forced one-word HIGH/WEAK call, same shape/cost tier as
# Taiwan's GDELT relevance check (_classify_gdelt_relevance) - defaults to
# the same cheaper second-pass model rather than the full OPENAI_MODEL,
# independently tunable via its own env var.
GEOPOLITICAL_SIGNAL_MODEL: str = os.environ.get("GEOPOLITICAL_SIGNAL_MODEL") or OPENAI_MODEL_V2
GEOPOLITICAL_SIGNAL_STAGE_B_DAILY_CAP: int = int(
    os.environ.get("GEOPOLITICAL_SIGNAL_STAGE_B_DAILY_CAP", "1000")
)
GEOPOLITICAL_SIGNAL_STAGE_C_DAILY_CAP: int = int(
    os.environ.get("GEOPOLITICAL_SIGNAL_STAGE_C_DAILY_CAP", "50")
)
# Stage B and Stage C (both single-model-call-per-row) share
# CLASSIFY_CONCURRENCY and the module-level _executor in controllers/run.py -
# same pool the news domain already uses, no dedicated knob needed since
# their own daily caps (1000/50) bound total volume anyway.

# Taiwan's translate/gdelt-relevance loops (pipeline/taiwan_signal_classifier.py)
# - both are single blocking HTTP calls per item, same shape as the other
# CLASSIFY_CONCURRENCY knobs.
TAIWAN_CLASSIFY_CONCURRENCY: int = int(os.environ.get("TAIWAN_CLASSIFY_CONCURRENCY", "5"))

# research-universe: Stage C's category->ticker map (Layer 3) is generated
# by a separate periodic refresh job that calls GET /companies, not fetched
# live during Stage C itself - same "free, deterministic lookup" property
# the spec intends. New to this service (news-retrieval already has the
# same pair, same naming, for its own company_news domain).
RESEARCH_UNIVERSE_URL: str = os.environ.get("RESEARCH_UNIVERSE_URL", "http://research-universe:8007")
RESEARCH_UNIVERSE_API_KEY: str | None = os.environ.get("RESEARCH_UNIVERSE_API_KEY") or None

GEOPOLITICAL_SIGNAL_STAGE_C_PROMPT: Path = PROMPTS_DIR / "geopolitical_signal_stage_c_v1.txt"
# Structured JSON output (5 fields) is a step up from Stage B's forced
# one-word call - defaults to the same model as Stage B rather than a
# separate env var's worth of config, but independently overridable if
# Stage C's real output quality needs a stronger tier.
GEOPOLITICAL_SIGNAL_STAGE_C_MODEL: str = (
    os.environ.get("GEOPOLITICAL_SIGNAL_STAGE_C_MODEL") or GEOPOLITICAL_SIGNAL_MODEL
)
