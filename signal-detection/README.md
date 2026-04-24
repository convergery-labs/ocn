# signal-detection

Part of the [ocn monorepo](../README.md). See root README for full system setup.

Classifies articles against topic clusters to detect signals, weak signals, and
noise using vector similarity (Qdrant) and LLM scoring.

## Stack

- **Framework**: FastAPI + Uvicorn (port 8002)
- **Database**: PostgreSQL (psycopg2)
- **Vector store**: Qdrant
- **Auth**: Bearer token validated via auth-service

## Quick Start

```bash
# From the repo root
docker compose up postgres-signal qdrant signal-detection
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SIGNAL_POSTGRES_PASSWORD` | Yes | — | PostgreSQL password |
| `SIGNAL_POSTGRES_DB` | No | `signal-detection` | PostgreSQL database name |
| `SIGNAL_POSTGRES_USER` | No | `signal-detection` | PostgreSQL user |
| `SIGNAL_POSTGRES_HOST` | No | `localhost` | PostgreSQL host |
| `QDRANT_HOST` | No | `qdrant` | Qdrant hostname |
| `QDRANT_PORT` | No | `6333` | Qdrant port |
| `NEWS_RETRIEVAL_URL` | Yes | — | news-retrieval base URL for run validation |
| `AUTH_SERVICE_URL` | Yes | — | auth-service base URL for token validation |

## API

All endpoints require `Authorization: Bearer <api-key>`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `POST` | `/classify` | Submit a classification job (returns 202) |
| `GET` | `/classifications/{job_id}` | Job status and aggregate stats |
| `GET` | `/classifications/{job_id}/results` | Paginated per-article results |

### POST /classify

Accepts either a `run_id` (fetches articles from news-retrieval) or an inline
`articles` list — not both.

```json
{
  "run_id": 42,
  "callback_url": "https://example.com/webhook"
}
```

```json
{
  "articles": [
    {"url": "...", "title": "...", "body": "...", "source": "...", "published": "..."}
  ],
  "callback_url": "https://example.com/webhook"
}
```

Returns `{"job_id": 1, "status": "processing"}`. On completion, POSTs
`{"job_id": 1, "status": "completed"}` to `callback_url` if provided.

### GET /classifications/{job_id}/results

Supports cursor-based pagination via `limit` (1–100, default 20) and `cursor`
query parameters.

## Testing

Postgres and Qdrant must be running before executing the test suite.

```bash
# From the repo root
docker compose up postgres-signal qdrant -d
pip install -r signal-detection/requirements-test.txt
pytest signal-detection/tests/
```

Test modules:

| Module | Coverage |
|--------|----------|
| `test_smoke.py` | Health endpoint, app startup |
| `test_classify.py` | POST /classify and GET /classifications/* endpoints |
