# research-universe

Part of the [ocn monorepo](../CLAUDE.md).

## Overview

`research-universe` discovers, classifies, and maintains the AlphaStreet AI Research Universe — a curated list of AI-relevant public and private companies. It uses a queue-based pipeline to stage, enrich, classify, and promote candidates via Google Sheets.

It exposes two execution modes:
- **serve**: long-running FastAPI process (health endpoint, port 8006)
- **run**: one-shot CLI command for running the full discovery pipeline

A one-time **init-sheet** command bootstraps the Google Sheet from the source XLSX.

## Jira Board
| Board | URL | Project Key |
|-------|-----|-------------|
| OCN Board | https://opengrowthventures.atlassian.net/jira/software/projects/CON/boards/34 | CON |

## Structure

See [STRUCTURE.md](STRUCTURE.md) for descriptions.

```
research-universe/
├── Dockerfile
├── requirements.txt
├── requirements-test.txt
├── pyproject.toml
├── CLAUDE.md
├── STRUCTURE.md
├── README.md
├── tests/
└── src/
    ├── __main__.py             # Click group: serve, run, init-sheet
    ├── app.py                  # FastAPI factory
    ├── config.py               # CATEGORIES, SEARCH_KEYWORDS, thresholds, env vars
    ├── models.py               # DiscoveryRow dataclass
    ├── sheets/
    │   ├── client.py           # SheetsClient: read_tab, append_rows, update_rows, overwrite_tab
    │   └── init.py             # run_init_sheet: XLSX → Google Sheet bootstrap
    ├── controllers/
    │   ├── loader.py           # Load Research Universe → dedup registry
    │   ├── discover.py         # Per-source discovery → list[DiscoveryRow]
    │   ├── normalize.py        # Coerce source output to consistent DiscoveryRow fields
    │   ├── enrich.py           # URL-first enrichment: official URL + page summary
    │   ├── stage.py            # Dedupe check → gate → write to Discovery Queue
    │   ├── classify.py         # Batch classify pending rows via LLM
    │   ├── promote.py          # Promote classified rows to New Companies / Research Universe
    │   └── writer.py           # Regenerate Public Companies + Private Watchlist views
    └── adapters/
        ├── alpha_vantage_client.py  # symbol_search, overview
        ├── llm_client.py            # OpenRouter: classify_batch
        ├── search_client.py         # Tavily: search (used by enrich)
        ├── signal_client.py         # signal-detection HTTP client (V2)
        └── crunchbase_client.py     # Crunchbase (V2, optional)
```

## Guidance

- Use the Jira board (project key `CON`) to track and reference cards
- Run `init-sheet` once to bootstrap the Google Sheet from the source XLSX; set `GOOGLE_SHEET_ID` in `.env` afterwards
- `GOOGLE_SERVICE_ACCOUNT` accepts a file path (local dev) or a JSON string (ECS)
- The pipeline is queue-based: all candidates go through Discovery Queue before any promotion to Research Universe
- Enrichment is URL-first: never classify from source metadata alone

## Maintenance

- Do not modify the Jira Board or Maintenance sections unless explicitly asked
- When adding discovery sources, add an adapter in `src/adapters/` and wire it into `src/controllers/discover.py`
- When adding categories, update `CATEGORIES` in `src/config.py`
