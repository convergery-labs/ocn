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
├── __main__.py          Entry point — Click group: serve, bootstrap, promote-corpus
├── app.py               App factory — assembles FastAPI, registers routers
├── auth.py              Infrastructure — Bearer token validation via auth-service
├── db.py                Infrastructure — psycopg2 wrapper, init_db(), transaction()
├── seed.py              Entry point helper — seeds classification_statuses on startup
├── routes/
│   ├── health.py        Route — GET /health
│   └── classify.py      Route — POST /classify, GET /classifications/*
├── controllers/
│   ├── classify.py      Controller — job submission and background execution
│   ├── bootstrap.py     Controller — corpus bootstrap pipeline orchestration
│   └── promote.py       Controller — nightly deferred corpus promotion job
└── models/
    ├── jobs.py           Repository — classification_jobs, classifications, deferred_promotions
    └── clusters.py       Repository — topic_clusters, corpus_centroids (incl. EWMA update)
```

Dependencies flow one way: `__main__` → `app` → `routes` → `controllers` → `models` → `db`.

## Bootstrap Pipeline

Invoked via `python -m src bootstrap --domain <slug> [--days-back 180] [--k 8]`.

1. **Fetch** — paginates `GET /runs?domain=<slug>&status=completed` then `GET /runs/{id}/articles` from `news-retrieval`; deduplicates by URL; skips articles with no body.
2. **Embed** — batches of 50 articles sent to OpenRouter (`openai/text-embedding-3-large`, 3072 dimensions). Bodies are truncated to 30,000 characters to stay within the model's 8,191-token limit. Point IDs are deterministic `uuid5(NAMESPACE_URL, url)` so re-runs skip already-embedded documents.
3. **Cluster** — all vectors scrolled from Qdrant; `MiniBatchKMeans(n_clusters=k)` run locally.
4. **Persist** — one Qdrant collection per cluster (`corpus_{domain}_{i}`); `topic_clusters` and `corpus_centroids` rows upserted to Postgres.

## EWMA Centroid Update

After every classification (implemented by CON-137), the article embedding updates the EWMA centroid for its assigned cluster:

```
centroid_t = alpha * embed(doc) + (1 - alpha) * centroid_{t-1}
```

- **Noise** articles: centroid updated immediately, atomically with the classification record.
- **Signal** articles: inserted into `deferred_promotions` with `promote_at = now() + 30 days`; centroid is NOT updated at classification time.

`alpha` is stored per-cluster in `topic_clusters.alpha` (default 0.15). The centroid vector is stored in `corpus_centroids.centroid_vector` (`REAL[]`).

## Deferred Corpus Promotion

Invoked via `python -m src promote-corpus` (run nightly).

For each `deferred_promotions` row where `promote_at <= NOW()` and `promoted_at IS NULL`:

1. Computes cosine similarity of the stored `article_embedding` against the current `centroid_vector`.
2. If similarity > `SIGNAL_THRESHOLD` (default 0.5): applies EWMA update, sets `final_label = Signal`.
3. Otherwise: sets `final_label = Noise` (false positive — centroid not updated).

Each promotion is committed in its own transaction so a single failure does not abort the batch.

## Vector Store

**Collections:**

| Collection | Contents | Created by |
|------------|----------|------------|
| `bootstrap_{domain}` | All article embeddings for a domain (staging) | `bootstrap` CLI |
| `corpus_{domain}_{i}` | Documents assigned to cluster `i` | `bootstrap` CLI |

**Vector config:** size = 3072, distance = Cosine (matches `text-embedding-3-large` output).

## Database Schema

| Table | Key columns |
|-------|-------------|
| `topic_clusters` | `id`, `slug`, `centroid_qdrant_collection`, `alpha` |
| `corpus_centroids` | `cluster_id`, `centroid_vector REAL[]`, `document_count`, `embedding_model` |
| `classification_jobs` | `id`, `run_id`, `status`, `article_count`, `callback_url` |
| `classifications` | `id`, `job_id`, `article_url`, `label`, `composite_score`, `article_embedding REAL[]`, `cluster_id` |
| `deferred_promotions` | `id`, `classification_id`, `promote_at`, `promoted_at`, `final_label` |
| `claims` | `id`, `classification_id`, `claim_text`, `claim_embedding_id` |

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
