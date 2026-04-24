# Structure

## Root

| Path | Description |
|------|-------------|
| `Dockerfile` | Builds a `python:3.11-slim` image; copies `src/` to `/app` and installs pip dependencies |
| `pyproject.toml` | pytest configuration: `asyncio_mode = "auto"`, `testpaths = ["tests"]` |
| `requirements-test.txt` | Test-only pip dependencies (`pytest`, `pytest-asyncio`) |
| `README.md` | Project overview and quick-start instructions |
| `CLAUDE.md` | AI assistant instructions: documentation index, Jira board, structural guide, maintenance rules |
| `STRUCTURE.md` | This file |
| `tests/` | Automated test suite — see Testing section below |
| `src/__main__.py` | CLI entry point — `click` + `uvicorn.run` |
| `src/app.py` | FastAPI app factory and lifespan hook |
| `src/pipeline.py` | Fetch and relevance-filter pipeline (fetch → Pass 1 LLM relevance filter); returns list of relevant articles |
| `src/db.py` | PostgreSQL connection (`psycopg2`), `_Connection` wrapper with portable placeholder normalisation and `execute_values` for batch inserts, `DuplicateError`, ambient transaction via `ContextVar`, schema init + migrations |
| `src/auth.py` | FastAPI dependency functions: `require_auth` (validate Bearer token), `require_admin` (role gate) |
| `src/seed.py` | Idempotent batch seed for `run_statuses`, `frequencies`, `domains`, `sources`, and admin API key |
| `src/models/` | Pydantic request models + SQL query functions per entity |
| `src/routes/` | FastAPI `APIRouter` definitions, one file per resource |

## App layers

The application is a single FastAPI process. `POST /run` uses FastAPI `BackgroundTasks` to execute the pipeline after the HTTP response is sent. Control flow is entirely Python-driven (not LLM-driven). All domain configuration (sources, polling frequencies) lives in PostgreSQL and is loaded at request time — no code changes are needed to add new domains.

| Layer | File(s) | Responsibility |
|-------|---------|----------------|
| **Entry point** | `src/__main__.py` | CLI wiring (`click`), starts `uvicorn` |
| **App factory** | `src/app.py` | Creates `FastAPI` instance, registers routers, runs lifespan (`init_db` + `seed`) |
| **Routes** | `src/routes/` | Thin HTTP adapters: one `APIRouter` per resource, maps domain exceptions to status codes |
| **Controllers** | `src/controllers/` | Business logic and multi-step orchestration; owns transaction boundaries for composite operations |
| **Repository** | `src/models/` | SQL query functions + Pydantic input models; no HTTP concepts |
| **Pipeline** | `src/pipeline.py` | Stateless pipeline: parallel RSS fetch, title-based relevance filter (Pass 1 LLM); returns list of relevant article dicts |
| **Database** | `src/db.py` | PostgreSQL connection (`psycopg2`), `_Connection` wrapper, `DuplicateError`, ambient transaction via `ContextVar`, schema init + migrations |
| **Auth** | `src/auth.py` | `require_auth` / `require_admin` FastAPI dependencies; delegates all token validation to `POST {AUTH_SERVICE_URL}/validate`; returns 503 if unconfigured |
| **Seed data** | `src/seed.py` | Idempotent batch seed for `run_statuses`, `frequencies`, `domains`, and `sources` |

### HTTP API

| Endpoint | Description |
|----------|-------------|
| `POST /run` | Submit a pipeline run; returns `202` with `run_id` immediately, or `200` with `cache_hit: true` if an identical run completed today UTC; optional `model` + `openrouter_api_key` override the server defaults; optional `callback_url` receives a webhook on completion or failure; `force: true` bypasses both the cache guard and concurrent-run guard |
| `GET /runs` | List runs, newest-first; filter by `domain`, `status`, `from_date`, `to_date`; cursor-paginated (`limit`, `cursor`); returns `{"runs": [...], "next_cursor": str\|null}` |
| `GET /runs/{id}` | Single run record |
| `GET /runs/{id}/articles` | Articles for a run; cursor-paginated (`limit`, `cursor`); returns `{"articles": [...], "next_cursor": str\|null}` |
| `GET /articles/{id}` | Single article record |
| `GET /health` | Service health check |
| `GET/POST /domains` | Manage domains (all require auth; `GET` scoped to caller's owned + null-owner domains; `POST` records caller as owner; `PATCH /{id}` requires ownership or admin) |
| `GET/POST /sources` | Manage sources (`POST` requires auth; users restricted to domains they own) |
| `GET/POST /frequencies` | Manage frequencies (`POST` admin only) |
| `POST /grants/{id}/domains` | Grant domain access to a key — admin only; upserts grants, returns updated domain list |
| `DELETE /grants/{id}/domains/{domain_id}` | Revoke a single domain grant — admin only; 204 on success, 404 if absent |

### Execution flow

```
POST /run  (returns 202 immediately, or 200 on cache hit)
  └─ create_run_record()        # validate domain + ownership
       ├─ get_cached_run_today() # cache hit → return 200 with cached run + cache_hit: true
       ├─ get_running_run_for_domain() # concurrent guard → 409
       └─ create_run()          # INSERT run row → run_id
  └─ BackgroundTasks.add_task(run_pipeline)  # skipped on cache hit

run_pipeline()  (background, after response is sent)
  └─ get_domain_config()        # load domain name + description from DB
  └─ pl.run()
       ├─ load_sources()        # query sources WHERE min_days_back <= days_back
       ├─ _fetch_articles()     # parallel feedparser (10 workers)
       └─ _filter_articles()    # Pass 1 — LLM: title-only relevance filter
  └─ create_articles()          # batch INSERT relevant articles
  └─ complete_run() / fail_run() # UPDATE runs SET status='completed'|'failed'
  └─ _fire_webhook()             # POST to callback_url if set (best-effort, 10s timeout)

GET /runs/{id}  →  live status poll
```

### Key behavioural rules

- Sources with `frequency.min_days_back > days_back` are skipped.
- Pass 1 (relevance filter) fails open: if a batch errors, those articles are kept.
- Domain config is loaded fresh from the DB on every `POST /run` — adding a new domain via the API takes effect immediately without restarting.
- The LLM never decides what tools to call — all orchestration is in Python.
- Same-day cache guard: if a completed run with identical `(domain, days_back, focus, model)` already exists for the current UTC day, `POST /run` returns it immediately with `cache_hit: true` (HTTP 200) without dispatching a new pipeline. `force: true` bypasses this.

## Testing

Tests live in `tests/` at the project root and run against a dedicated `news-retrieval-test` PostgreSQL database. The pipeline's LLM calls are mocked at the `pipeline.run` boundary; all other app code runs in-process via `httpx.AsyncClient` + `ASGITransport`.

### Running the tests

```bash
# From the repo root — start the test DB
docker compose up postgres-news-test -d

# Install test dependencies
pip install -r news-retrieval/requirements-test.txt

# Run suite
pytest news-retrieval/tests/
```

`conftest.py` creates and wipes the test database on each `pytest` session, so no manual DB setup is needed beyond having postgres available.

### Test modules

| Module | Coverage |
|--------|----------|
| `test_auth.py` | Missing/invalid auth header → 422/401; non-admin on admin endpoint → 403; delegated-path: valid key, rejected key, 503 when `AUTH_SERVICE_URL` unset |
| `test_runs.py` | `POST /run`: 202 + DB record created; unknown domain → 404; non-owner → 403 |
| `test_guard_chain.py` | CON-111 concurrent guard → 409 with `run_id`; `force=true` bypasses guard |
| `test_cache_guard.py` | CON-120 same-day cache guard → 200 with `cache_hit: true`; different params miss cache; `force=true` bypasses; yesterday's run is not a hit |
| `test_subset_guard.py` | Time-window subset guard; reuses articles from wider same-day run |
| `test_pagination.py` | Cursor advances on `GET /runs` and `GET /runs/{id}/articles`; last page has `next_cursor: null` |
| `test_webhook.py` | `callback_url` POSTed with `status=completed` on success and `status=failed` on pipeline error |
| `test_ownership.py` | `POST /sources` and `PATCH /domains/{id}` reject non-owners → 403; null-owner domains visible to all users; multi-key grants; grant revocation; admin bypass |
| `test_pipeline.py` | LLM batch error keeps all articles (fail-open) |

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
| `OPENROUTER_API_KEY` | — | Required. Server-level API key for OpenRouter |
| `OPENROUTER_MODEL` | — | Required. Default model string for relevance filtering, e.g. `inclusionai/ling-2.6-flash:free` |
| `AUTH_SERVICE_URL` | — | Required. URL of the auth-service (e.g. `http://auth-service:8001`). All Bearer tokens are validated by `POST {AUTH_SERVICE_URL}/validate`; returns 503 if unset |
| `POSTGRES_HOST` | `localhost` | PostgreSQL server hostname |
| `POSTGRES_PORT` | `5432` | PostgreSQL server port |
| `POSTGRES_DB` | `news-retrieval` | Database name |
| `POSTGRES_USER` | `news-retrieval` | Database user |
| `POSTGRES_PASSWORD` | — | Database password |

### External services

| Service | Used for |
|---------|---------|
| OpenRouter (`openrouter.ai/api/v1`) | LLM inference — relevance filtering, tag generation, cluster naming, embeddings |
| RSS feeds (various) | Source articles — managed via `POST /sources` API or seed data in `src/seed.py` |

### Database schema

Seven normalized tables. `run_statuses`, `frequencies`, `domains`, and `sources` are populated at startup; new rows can be added through the API at runtime. `runs` and `articles` are populated by pipeline runs. API key lifecycle is managed entirely by auth-service — news-retrieval stores only per-key domain grants.

| Table | Key columns | Notes |
|-------|-------------|-------|
| `api_key_domains` | `api_key_id`, `domain_id` (composite PK) | Junction table: explicit domain-access grants per key (key IDs come from auth-service) |
| `run_statuses` | `name` (PK) | Lookup table: `running`, `completed`, `failed` |
| `frequencies` | `name`, `min_days_back` | e.g. daily=1, weekly=7, monthly=30 |
| `domains` | `name`, `slug`, `description`, `created_by` | `created_by` is audit-only (plain integer, no FK); access control uses `api_key_domains`; null = globally accessible |
| `sources` | `url`, `domain_id`, `frequency_id`, `name`, `description` | FK to `domains` and `frequencies` |
| `runs` | `name`, `domain`, `started_at`, `completed_at`, `status`, `article_count`, `summary`, `callback_url`, `model` | One row per `POST /run`; `status` FK to `run_statuses`; `model` records the LLM used |
| `articles` | `run_id`, `url`, `title`, `summary`, `source`, `published` | FK to `runs` |
