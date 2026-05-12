import os

CATEGORIES = [
    "Minerals & Raw Materials",
    "Energy",
    "Semiconductor Manufacturing",
    "Compute Hardware",
    "Thermal & Cooling",
    "Data Center Infrastructure",
    "Cloud & Compute Market",
    "Software/Infrastructure",
    "AI Data",
    "AI Models",
    "Applications & Economy",
]

SEARCH_KEYWORDS = [
    "artificial intelligence",
    "semiconductor",
    "data center",
    "machine learning",
    "AI chip",
    "cloud compute",
]

CLASSIFY_BATCH_SIZE = 10
FUZZY_MATCH_THRESHOLD = 85
MIN_SUMMARY_LENGTH = 80

GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT = os.environ.get("GOOGLE_SERVICE_ACCOUNT", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
ALPHA_VANTAGE_API_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
SIGNAL_DETECTION_URL = os.environ.get("SIGNAL_DETECTION_URL", "")
SIGNAL_CALLER_SUB = os.environ.get("SIGNAL_CALLER_SUB", "1")
CRUNCHBASE_API_KEY = os.environ.get("CRUNCHBASE_API_KEY", "")
