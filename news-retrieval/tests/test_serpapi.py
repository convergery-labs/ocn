import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from pipeline import _fetch_one_serpapi
from seed import SERPAPI_QUERIES

api_key = os.environ.get("SERPAPI_KEY")
if not api_key:
    print("SERPAPI_KEY not set")
    sys.exit(1)

query, name, _ = SERPAPI_QUERIES[0]
results = _fetch_one_serpapi({"url": query, "config": None}, days_back=1, api_key=api_key)
print(f"{name} → {len(results)} articles")
for a in results[:3]:
    print(f"  - [{a['source']}] {a['title']}")
    print(f"    published: {a['published']}")
