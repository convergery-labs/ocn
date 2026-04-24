# Structure

## Root

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build: `base` (production), `dev` (hot-reload), `test` (pytest) |
| `requirements.txt` | Production dependencies |
| `requirements-test.txt` | Test-only dependencies (pytest, httpx) |
| `pyproject.toml` | pytest configuration |

## App Layers

```
src/
├── __main__.py          Entry point — Click group with serve and bootstrap subcommands
├── app.py               App factory — assembles FastAPI, registers routers
├── auth.py              Infrastructure — Bearer token validation via auth-service
├── db.py                Infrastructure — psycopg2 wrapper, init_db(), transaction()
├── seed.py              Entry point helper — seeds classification_statuses on startup
├── routes/
│   ├── health.py        Route — GET /health
│   └── classify.py      Route — POST /classify, GET /classifications/*
├── controllers/
│   ├── classify.py      Controller — job submission and background execution
│   └── bootstrap.py     Controller — corpus bootstrap pipeline orchestration
└── models/
    ├── jobs.py           Repository — classification_jobs, classifications tables
    └── clusters.py       Repository — topic_clusters, corpus_centroids tables
```

Dependencies flow one way: `__main__` → `app` → `routes` → `controllers` → `models` → `db`.

## Bootstrap Pipeline

Invoked via `python -m src bootstrap --domain <slug> [--days-back 180] [--k 8]`.

1. **Fetch** — paginates `GET /runs?domain=<slug>&status=completed` then `GET /runs/{id}/articles` from `news-retrieval`; deduplicates by URL; skips articles with no body.
2. **Embed** — batches of 50 articles sent to OpenRouter (`openai/text-embedding-3-large`, 3072 dimensions). Bodies are truncated to 30,000 characters to stay within the model's 8,191-token limit. Point IDs are deterministic `uuid5(NAMESPACE_URL, url)` so re-runs skip already-embedded documents.
3. **Cluster** — all vectors scrolled from Qdrant; `MiniBatchKMeans(n_clusters=k)` run locally.
4. **Persist** — one Qdrant collection per cluster (`corpus_{domain}_{i}`); `topic_clusters` and `corpus_centroids` rows upserted to Postgres.

## Vector Store

**Collections:**

| Collection | Contents | Created by |
|------------|----------|------------|
| `bootstrap_{domain}` | All article embeddings for a domain (staging) | `bootstrap` CLI |
| `corpus_{domain}_{i}` | Documents assigned to cluster `i` | `bootstrap` CLI |

**Vector config:** size = 3072, distance = Cosine (matches `text-embedding-3-large` output).

## HTTP API

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | None | Liveness check — Postgres, Qdrant, auth-service |
| `POST` | `/classify` | Bearer | Submit a classification job (202 Accepted) |
| `GET` | `/classifications/{job_id}` | Bearer | Job status and aggregate stats |
| `GET` | `/classifications/{job_id}/results` | Bearer | Paginated per-article results |

## Testing

Integration tests require Postgres and Qdrant to be running:

```bash
docker compose up postgres-signal qdrant -d
pip install -r signal-detection/requirements-test.txt
pytest signal-detection/tests/
```

| Module | Coverage |
|--------|----------|
| `test_smoke.py` | Health endpoint, app startup |
| `test_classify.py` | POST /classify, GET /classifications/* |
