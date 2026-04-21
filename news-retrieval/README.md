# news-retrieval

Fetches RSS feeds and filters articles by relevance to a domain using LLMs. Returns structured JSON with articles grouped by run.

## Stack

- **Server**: FastAPI + uvicorn
- **Database**: PostgreSQL (persisted via Docker volume)
- **LLM**: Configurable via `OPENROUTER_MODEL` (e.g. `openrouter/elephant-alpha`) via OpenRouter

## Quick start

```bash
# Copy .env.example and fill in required values
cp .env.example .env

docker compose up
```

The API is available at `http://localhost:8000`. Interactive docs at `/docs`.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | Yes | Server-level API key for OpenRouter |
| `OPENROUTER_MODEL` | Yes | Default model for relevance filtering, e.g. `openrouter/elephant-alpha` |
| `ADMIN_API_KEY` | Yes | Plaintext admin API key seeded into the DB on first startup |
| `POSTGRES_HOST` | No | PostgreSQL host (default: `localhost`) |
| `POSTGRES_PORT` | No | PostgreSQL port (default: `5432`) |
| `POSTGRES_DB` | No | Database name (default: `news-retrieval`) |
| `POSTGRES_USER` | No | Database user (default: `news-retrieval`) |
| `POSTGRES_PASSWORD` | Yes | Database password |

## API

All write endpoints require an `Authorization: Bearer <token>` header. Admin-only endpoints require a key with the `admin` role.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/run` | Required | Submit a pipeline run; returns `202` with `run_id`, or `200` with `cache_hit: true` if an identical run completed today |
| `GET` | `/runs` | — | List runs newest-first; filter by `domain`, `status`, `from_date`, `to_date`; cursor-paginated |
| `GET` | `/runs/{id}` | — | Single run record |
| `GET` | `/runs/{id}/articles` | — | Articles for a run; cursor-paginated |
| `GET` | `/articles/{id}` | — | Single article record |
| `GET` | `/domains` | — | List domains (caller's owned + null-owner domains) |
| `POST` | `/domains` | Required | Create a domain |
| `PATCH` | `/domains/{id}` | Required | Update a domain (owner or admin only) |
| `GET` | `/sources` | — | List sources (optional `?domain=` filter) |
| `POST` | `/sources` | Required | Add an RSS feed source |
| `GET` | `/frequencies` | — | List polling frequencies |
| `POST` | `/frequencies` | Admin | Add a polling frequency |
| `GET` | `/api-keys` | Admin | List API keys |
| `POST` | `/api-keys` | Admin | Create an API key (returns plaintext key once) |
| `GET` | `/health` | — | Health check |

### POST /run

Submits a pipeline run. Returns `202` immediately with a `run_id`; the pipeline runs in the background.

If a completed run with identical parameters (`domain`, `days_back`, `focus`, `model`) already exists for the current UTC day, returns `200` with the existing run's fields and `cache_hit: true` — no pipeline is dispatched. Use `force: true` to bypass this and always start a fresh run.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `domain` | string | Yes | Slug of the domain to run against (e.g. `ai_news`) |
| `days_back` | integer | No (default: `7`) | How far back to fetch articles; sources with `min_days_back > days_back` are skipped |
| `max_articles` | integer | No | Cap on articles stored; omit for no limit |
| `focus` | string | No | Instruction to narrow the topics the relevance filter accepts |
| `callback_url` | string | No | URL to POST a status payload to on completion or failure |
| `force` | boolean | No (default: `false`) | Bypass the concurrent-run guard and same-day cache guard for this domain |
| `model` | string | No | OpenRouter model string; overrides `OPENROUTER_MODEL` for this run |
| `openrouter_api_key` | string | Required if `model` is set | OpenRouter API key to use with the model override |

```bash
curl -X POST http://localhost:8000/run \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"domain": "ai_news", "days_back": 7}'
```

Response: `{"run_id": "<uuid>"}` — poll `GET /runs/{run_id}` for status.

### POST /domains

Creates a domain. The caller is recorded as the owner.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Human-readable display name |
| `slug` | string | Yes | Unique identifier used in `POST /run` |
| `description` | string | No | Used by the LLM as context for relevance filtering |

```bash
curl -X POST http://localhost:8000/domains \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "AI News", "slug": "ai_news", "description": "Artificial intelligence research and industry news"}'
```

### PATCH /domains/{id}

Updates a domain. Caller must own the domain or have the `admin` role. All fields are optional; only provided fields are updated.

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | New display name |
| `slug` | string | New slug |
| `description` | string | New description |

### POST /sources

Adds an RSS feed source to a domain. Non-admin users can only add sources to domains they own.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | Yes | RSS/Atom feed URL |
| `domain_id` | integer | Yes | ID of the domain this source belongs to |
| `frequency_id` | integer | Yes | ID of the polling frequency (see `GET /frequencies`) |
| `name` | string | No | Display name for the source |
| `description` | string | No | Description of what the source covers |

```bash
curl -X POST http://localhost:8000/sources \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/feed.rss", "domain_id": 1, "frequency_id": 1}'
```

### POST /frequencies

Admin only. Adds a polling frequency that can be assigned to sources.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Display name (e.g. `daily`, `weekly`) |
| `min_days_back` | integer | Yes | Minimum `days_back` a run must request for this source to be included (≥ 1) |

### POST /api-keys

Admin only. Creates an API key. The plaintext key is returned once in the response and cannot be retrieved again.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `label` | string | Yes | Human-readable label for the key |
| `role` | string | Yes | Either `"admin"` or `"user"` |

## Testing

```bash
# Start postgres (if not already running)
docker compose up postgres -d

# Install test dependencies
pip install -r requirements-test.txt

# Run suite
pytest
```

Tests run against a dedicated `news-retrieval-test` database. The test DB is created and wiped automatically each `pytest` session.
