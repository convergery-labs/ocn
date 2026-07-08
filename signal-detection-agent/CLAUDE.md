# signal-detection-agent

Part of the [ocn monorepo](../CLAUDE.md).

## Overview

`signal-detection-agent` is a FastAPI service (port 8003) that classifies news articles as
**signal**, **weak_signal**, or **noise** using an LLM-driven pipeline. Unlike `signal-detection`
(which uses vector similarity + corpus centroids), this service sends each article's text directly
to an LLM and gets back a structured classification with a score, reason, materiality, category,
and named entities.

Articles are fetched from `news-retrieval`. The service can trigger a fresh run or reuse the
latest completed run (useful for testing). Classification results are stored locally; full article
content remains in news-retrieval.

## Jira Board
| Board | URL | Project Key |
|-------|-----|-------------|
| OCN Board | https://opengrowthventures.atlassian.net/jira/software/projects/CON/boards/34 | CON |

## Structure

See [STRUCTURE.md](STRUCTURE.md) for descriptions.

```
signal-detection-agent/
├── Dockerfile
├── requirements.txt
├── requirements-test.txt
├── pyproject.toml
├── CLAUDE.md
├── STRUCTURE.md
├── prompts/
│   ├── ai_universe_signal_classifier_v1.txt
│   └── ai_universe_signal_classifier_v2_refine.txt
├── src/
│   ├── __main__.py
│   ├── app.py
│   ├── auth.py
│   ├── config.py
│   ├── db.py
│   ├── seed.py
│   ├── routes/
│   │   ├── health.py
│   │   ├── run.py
│   │   └── jobs.py
│   ├── controllers/
│   │   └── run.py
│   ├── models/
│   │   └── jobs.py
│   ├── pipeline/
│   │   ├── classifier.py
│   │   └── category_candidates.py   (parked - not wired in v1)
│   └── adapters/
│       ├── news_client.py
│       └── web_search.py
└── tests/
    ├── conftest.py
    ├── test_caching.py
    └── test_smoke.py
```

## Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | LLM API key (OpenAI or OpenRouter) |
| `OPENAI_BASE_URL` | LLM base URL (default: `https://api.openai.com/v1`) |
| `SIGNAL_DETECTION_MODEL` / `OPENAI_MODEL` | Base pass model (default: `gpt-4.1`) |
| `SIGNAL_DETECTION_MODEL_V2` | Second pass model — falls back to `SIGNAL_DETECTION_MODEL` if unset |
| `NEWS_RETRIEVAL_URL` | news-retrieval base URL (default: `http://news-retrieval:8000`) |
| `POSTGRES_HOST/PORT/DB/USER/PASSWORD` | Signal-detection Postgres DB connection |
| `PIPELINE_POLL_TIMEOUT_SECS` | Max seconds to wait for a news-retrieval run (default: 600) |
| `WEB_SEARCH_PROVIDER` | Web search backend: `duckduckgo` (default), `tavily`, `brave` |
| `WEB_SEARCH_API_KEY` | API key for Tavily or Brave (not required for DuckDuckGo) |
| `CLASSIFY_CONCURRENCY` | Max concurrent article classifiers (default: 5) |

## Guidance

- Use the Jira board (project key `CON`) to track and reference cards
- `category_candidates.py` is parked - re-enable by passing `category_hints` into `classify_article()` if category errors appear in production

## Maintenance

- Do not modify the Jira Board, Guidance, or Maintenance sections unless explicitly asked
