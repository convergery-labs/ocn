# signal-detection

Part of the [ocn monorepo](../README.md). See root README for full system setup.

Classifies news articles as Signal, Weak Signal, or Noise using vector
similarity against a reference corpus stored in Qdrant. Downstream consumer of
`news-retrieval` — does not ingest articles directly.

## Stack

- **Framework**: FastAPI + Uvicorn (port 8002)
- **Database**: PostgreSQL (psycopg2)
- **Vector store**: Qdrant
- **Auth**: Bearer token validated via auth-service

## Quick Start

```bash
# From the repo root — start the HTTP service
docker compose up postgres-signal qdrant signal-detection

# Bootstrap the corpus (run once per domain before classifying)
docker compose run --rm signal-detection python -m src bootstrap \
    --domain ai_news --days-back 180 --k 8
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
| `OPENROUTER_API_KEY` | Yes (bootstrap) | — | OpenRouter API key for embeddings |
| `EMBEDDING_MODEL` | No | `openai/text-embedding-3-large` | Embedding model (OpenRouter prefix format) |
| `SIGNAL_THRESHOLD` | No | `0.5` | Cosine similarity threshold used by the deferred promotion job |

## Bootstrap CLI

Seeds the Qdrant corpus before the service can classify articles. Idempotent — re-runs skip already-embedded documents.

```bash
docker compose run --rm signal-detection python -m src bootstrap \
    --domain <slug> \
    --days-back 180 \
    --k 8
```

| Option | Default | Description |
|--------|---------|-------------|
| `--domain` | required | Domain slug (e.g. `ai_news`, `smart_money`) |
| `--days-back` | `180` | How many days of historical articles to fetch |
| `--k` | `8` | Number of topic clusters (k-means k) |

The command fetches completed runs from `news-retrieval`, embeds article bodies via OpenRouter (`text-embedding-3-large`, truncated to 30,000 characters), clusters with MiniBatchKMeans, and writes `topic_clusters` + `corpus_centroids` rows to Postgres with one Qdrant collection per cluster.

## Promote Corpus CLI

Runs the nightly deferred corpus promotion job. Processes all `deferred_promotions` rows that are due (`promote_at <= now()`), re-scores each article against the current centroid, and updates the centroid for confirmed Signal documents.

```bash
docker compose run --rm signal-detection python -m src promote-corpus
```

Can be run at any time for manual testing; idempotent (already-promoted rows are ignored).

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
