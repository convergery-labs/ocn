# Structure

## Root

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build: `base` (production), `dev` (hot-reload), `test` (pytest). Build context is repo root. |
| `requirements.txt` | Production dependencies |
| `requirements-test.txt` | Test-only dependencies |
| `pyproject.toml` | pytest configuration |

## App Layers

```
src/
├── __main__.py       Entry point — Click group: serve, run, init-sheet
├── app.py            App factory — FastAPI, GET /health
├── config.py         Configuration — CATEGORIES, SEARCH_KEYWORDS, thresholds, env vars
├── models.py         Shared data contract — DiscoveryRow dataclass
├── sheets/
│   ├── client.py     Infrastructure — gspread SheetsClient:
│   │                                  read_tab(), append_rows(), update_rows(), overwrite_tab()
│   └── init.py       One-time setup — run_init_sheet(xlsx_path) → sheet_id
├── controllers/
│   ├── loader.py     Controller — read Research Universe → build dedup registry
│   │                              (by_ticker, by_name, by_domain, all_names)
│   ├── discover.py   Controller — call source adapters → list[DiscoveryRow]
│   ├── normalize.py  Controller — coerce fields to consistent DiscoveryRow values
│   ├── enrich.py     Controller — URL-first enrichment (EnrichTask list):
│   │                              find official URL → fetch page summary → set statuses
│   ├── stage.py      Controller — dedupe check → gate → append to Discovery Queue tab
│   ├── classify.py   Controller — batch classify pending rows, update Discovery Queue
│   ├── promote.py    Controller — classified_add → New Companies;
│   │                              approved → Research Universe
│   └── writer.py     Controller — regenerate Public Companies + Private Watchlist views
└── adapters/
    ├── alpha_vantage_client.py  Infrastructure — symbol_search(), overview()
    ├── llm_client.py            Infrastructure — OpenRouter: classify_batch()
    ├── search_client.py         Infrastructure — Tavily: search()
    ├── signal_client.py         Infrastructure — signal-detection HTTP client (V2)
    └── crunchbase_client.py     Infrastructure — Crunchbase (V2, optional)
```

Dependencies flow one way: `__main__` → `app` → `controllers` → `adapters` + `sheets`.

## Execution Modes

| Mode | Command | Invoked by |
|------|---------|-----------|
| **serve** | `python -m src serve` | ECS long-running service (desired_count=1) |
| **run** | `python -m src run` | EventBridge cron (or manual trigger) |
| **init-sheet** | `python -m src init-sheet --file path/to/file.xlsx` | One-time setup |

## HTTP API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |

## Pipeline

```
run_pipeline()
  └─ loader.load()                      # build dedup registry from Research Universe tab
  └─ discover.run_all()                 # call all source adapters → list[DiscoveryRow]
  └─ normalize.run(rows)                # coerce fields to consistent values
  └─ enrich.run(rows)                   # URL-first: find official URL + fetch page summary
  └─ stage.run(rows, registry)          # dedupe check → gate → write to Discovery Queue
  └─ classify.run()                     # read pending rows, batch classify, update statuses
  └─ promote.to_new_companies()         # classified_add → New Companies tab
  # Human reviews New Companies; agent promotes approved rows to Research Universe
```

## Google Sheets Tab Structure

| Tab | Owner | Purpose |
|-----|-------|---------|
| Research Universe | Human + Agent (promote only) | Final universe — 6 cols |
| Public Companies | Agent (regenerate) | Filtered view of Research Universe |
| Private Watchlist | Agent (regenerate) | Filtered view of Research Universe |
| Category Guide | Human (read-only) | 11 categories reference |
| Ticker QA | Human (read-only) | QA summary |
| Discovery Queue | Agent | Staging area — all candidates with status fields |
| New Companies | Agent (write) + Human (review) | Classified-add rows ready for promotion |
| Change Log | Agent (append-only) | Audit trail of every action |

## Testing

```bash
# From repo root
pip install -r research-universe/requirements-test.txt
pytest research-universe/tests/
```
