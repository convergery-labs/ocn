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
# SIGNAL_DETECTION_MODEL_V2 directly (not OPENAI_MODEL_V2, which would
# chain further to OPENAI_MODEL/SIGNAL_DETECTION_MODEL - the Sonnet base
# model - if SIGNAL_DETECTION_MODEL_V2 were ever unset), so this always
# matches the same second-pass model configured in AWS, never silently
# upgrades to the base model. Independently tunable via its own env var.
GEOPOLITICAL_SIGNAL_MODEL: str = (
    os.environ.get("GEOPOLITICAL_SIGNAL_MODEL")
    or os.environ.get("SIGNAL_DETECTION_MODEL_V2")
    or OPENAI_MODEL_V2
)
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

# Macro Signal Backbone: INTERPRET is one short structured call per
# collapsed event (not per series/article). CONFIRMED LIVE over a real
# 2-week run: OPENAI_MODEL_V2 (gpt-4o-mini) produced a malformed/empty
# "assets" array on ~28% of real calls (5 of 18 collapsed events),
# intermittent rather than reproducible from the event shape alone - the
# validator correctly rejects it, but the event is then silently
# dropped with no fallback (see interpret_event's own no-retry
# rationale). Falls back to SEC_FILING_MODEL instead - a stronger model
# already proven reliable for this codebase's other structured-JSON
# extraction call, not the cheaper V2 tier Taiwan's forced-one-word
# calls use (a wrong word there just means "safely defaults to WEAK";
# a malformed macro event here means the event is lost entirely, a
# real cost this domain isn't willing to pay for the cheaper model).
MACRO_SIGNAL_DOMAIN: str = os.environ.get("MACRO_SIGNAL_DOMAIN", "macro_signal")
MACRO_SIGNAL_MODEL: str = os.environ.get("MACRO_SIGNAL_MODEL") or SEC_FILING_MODEL
MACRO_SIGNAL_PROMPT: Path = PROMPTS_DIR / "macro_signal_interpret_v1.txt"
# One blocking HTTP call per collapsed event, same shape as
# TAIWAN_CLASSIFY_CONCURRENCY - independently tunable since event volume
# (a handful/day) differs a lot from Taiwan's per-article volume.
MACRO_SIGNAL_CLASSIFY_CONCURRENCY: int = int(os.environ.get("MACRO_SIGNAL_CLASSIFY_CONCURRENCY", "5"))
# Rolling 2-year window per spec - each pipeline run re-pulls this much
# history per series rather than maintaining an incremental watermark
# (v1 simplicity tradeoff, see plan history).
MACRO_SIGNAL_ZSCORE_WINDOW_DAYS: int = int(os.environ.get("MACRO_SIGNAL_ZSCORE_WINDOW_DAYS", "730"))
