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

All write endpoints require a `Bearer <token>` header. Admin-only endpoints require a key with the `admin` role.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/run` | Required | Submit a pipeline run; returns `202` with `run_id` immediately |
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

### Run the pipeline

```bash
curl -X POST http://localhost:8000/run \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"domain": "ai_news", "days_back": 7}'
```

Optional fields: `model`, `openrouter_api_key` (override server defaults), `callback_url` (webhook on completion or failure).

Response: `{"run_id": "<uuid>"}` — poll `GET /runs/{run_id}` for status.

### Add a domain

```bash
curl -X POST http://localhost:8000/domains \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "My Domain", "slug": "my_domain", "description": "..."}'
```

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
