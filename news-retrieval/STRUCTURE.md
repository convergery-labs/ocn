# Structure

## Root

| Path | Description |
|------|-------------|
| `Dockerfile` | Builds a `python:3.11-slim` image; copies `src/` to `/app` and installs pip dependencies |
| `docker-compose.yml` | Runs the service on port 8000; enables hot-reload via `docker compose watch` |
| `README.md` | Project overview and quick-start instructions |
| `CLAUDE.md` | AI assistant instructions: documentation index, Jira board, structural guide, maintenance rules |
| `STRUCTURE.md` | This file |
| `src/__main__.py` | CLI entry point — `click` + `uvicorn.run` |
| `src/app.py` | FastAPI app factory and lifespan hook |
| `src/pipeline.py` | Fetch and relevance-filter pipeline (fetch → Pass 1 LLM relevance filter); returns list of relevant articles |
| `src/db.py` | PostgreSQL connection (`psycopg2`), `_Connection` wrapper with portable placeholder normalisation and `execute_values` for batch inserts, `DuplicateError`, ambient transaction via `ContextVar`, schema init + migrations |
| `src/seed.py` | Idempotent batch seed for `frequencies`, `domains`, and `sources` |
| `src/models/` | Pydantic request models + SQL query functions per entity |
| `src/routes/` | FastAPI `APIRouter` definitions, one file per resource |

## App layers

The application is a single FastAPI process with no background workers. Control flow is entirely Python-driven (not LLM-driven). All domain configuration (sources, taxonomy) lives in PostgreSQL and is loaded at request time — no code changes are needed to add new domains.

| Layer | File(s) | Responsibility |
|-------|---------|----------------|
| **Entry point** | `src/__main__.py` | CLI wiring (`click`), starts `uvicorn` |
| **App factory** | `src/app.py` | Creates `FastAPI` instance, registers routers, runs lifespan (`init_db` + `seed`) |
| **Routes** | `src/routes/` | Thin HTTP adapters: one `APIRouter` per resource, maps domain exceptions to status codes |
| **Controllers** | `src/controllers/` | Business logic and multi-step orchestration; owns transaction boundaries for composite operations |
| **Repository** | `src/models/` | SQL query functions + Pydantic input models; no HTTP concepts |
| **Pipeline** | `src/pipeline.py` | Stateless pipeline: parallel RSS fetch, title-based relevance filter (Pass 1 LLM); returns list of relevant article dicts |
| **Database** | `src/db.py` | PostgreSQL connection (`psycopg2`), `_Connection` wrapper, `DuplicateError`, ambient transaction via `ContextVar`, schema init + migrations |
| **Seed data** | `src/seed.py` | Idempotent batch seed for `frequencies`, `domains`, `taxonomies`, and `sources`; safe to re-run |

### HTTP API

| Endpoint | Description |
|----------|-------------|
| `POST /run` | Trigger a pipeline run for a domain |
| `GET /runs` | List all runs, newest first |
| `GET /runs/{id}` | Single run record |
| `GET /runs/{id}/articles` | All articles for a run |
| `GET /articles/{id}` | Single article record |
| `GET /health` | Service health check |
| `GET/POST /domains` | Manage domains |
| `GET/POST /sources` | Manage sources |
| `GET/POST /frequencies` | Manage frequencies |

### Execution flow

```
POST /run
  └─ get_domain_config()        # load domain name + description from DB
  └─ pl.run()
       ├─ load_sources()        # query sources WHERE min_days_back <= days_back
       ├─ _fetch_articles()     # parallel feedparser (10 workers)
       └─ _filter_articles()    # Pass 1 — LLM: title-only relevance filter
  └─ create_articles()          # batch INSERT relevant articles
  └─ complete_run()             # UPDATE runs SET status='completed'
```

### Key behavioural rules

- Sources with `frequency.min_days_back > days_back` are skipped.
- Pass 1 (relevance filter) fails open: if a batch errors, those articles are kept.
- Domain config is loaded fresh from the DB on every `POST /run` — adding a new domain via the API takes effect immediately without restarting.
- The LLM never decides what tools to call — all orchestration is in Python.

## Dependencies

### Python packages (installed in Docker image)

| Package | Purpose |
|---------|---------|
| `fastapi` | HTTP server framework |
| `uvicorn` | ASGI server |
| `pydantic` | Data validation and request/response models |
| `openai` | OpenAI-compatible SDK, pointed at Ollama |
| `feedparser` | RSS/Atom feed parsing |
| `numpy` | Vector arithmetic for embedding normalisation and cluster centroid updates |
| `httpx` | HTTP/1.1 client used inside the OpenAI SDK |
| `click` | CLI entry point (`--host`, `--port` flags) |
| `psycopg2-binary` | PostgreSQL database driver |

### Runtime requirements

| Variable / resource | Default | Description |
|--------------------|---------|-------------|
| `OPENROUTER_API_KEY` | — | Required. API key for OpenRouter (LLM + embedding calls) |
| `POSTGRES_HOST` | `localhost` | PostgreSQL server hostname |
| `POSTGRES_PORT` | `5432` | PostgreSQL server port |
| `POSTGRES_DB` | `news-retrieval` | Database name |
| `POSTGRES_USER` | `news-retrieval` | Database user |
| `POSTGRES_PASSWORD` | — | Database password |
| Docker network `agents-net` | external | Shared bridge network for inter-agent communication |

### External services

| Service | Used for |
|---------|---------|
| OpenRouter (`openrouter.ai/api/v1`) | LLM inference — relevance filtering, tag generation, cluster naming, embeddings |
| RSS feeds (various) | Source articles — managed via `POST /sources` API or seed data in `src/seed.py` |

### Database schema

Six normalized tables. `frequencies`, `domains`, `sources`, and `taxonomies` are populated at startup via `seed.py`; new rows can be added through the API at runtime. `runs`, `categories`, and `articles` are populated by pipeline runs.

| Table | Key columns | Notes |
|-------|-------------|-------|
| `frequencies` | `name`, `min_days_back` | e.g. daily=1, weekly=7, monthly=30 |
| `domains` | `name`, `slug`, `description` | e.g. `ai_news`, `smart_money` |
| `sources` | `url`, `domain_id`, `frequency_id`, `name`, `description` | FK to `domains` and `frequencies` |
| `runs` | `name`, `domain`, `started_at`, `completed_at`, `status`, `article_count` | One row per `POST /run`; status: running → completed / failed |
| `articles` | `run_id`, `url`, `title`, `summary`, `source`, `published` | FK to `runs` |
