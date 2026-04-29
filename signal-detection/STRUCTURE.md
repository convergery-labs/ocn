# Structure

## Root

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build: `base` (production), `dev` (hot-reload), `test` (pytest). Build context is the repo root (`docker build -f signal-detection/Dockerfile .`); copies `signal-detection/src/`, `signal-detection/requirements.txt`, and `shared/src/` into the image. |
| `requirements.txt` | Production dependencies |
| `requirements-test.txt` | Test-only dependencies (pytest, httpx) |
| `pyproject.toml` | pytest configuration |

## App Layers

```
src/
├── __main__.py          Entry point — Click group: serve, bootstrap, promote-corpus,
│                                      historical-ingest
├── app.py               App factory — assembles FastAPI, registers routers
├── auth.py              Infrastructure — x-ocn-caller header extraction (set by the API
│                                         gateway)
├── db.py                Infrastructure — thin adapter: _new_connection() (env vars),
│                                         init_db(), db_utils.configure(); public API
│                                         (get_db, transaction, DuplicateError) re-exported
│                                         from shared/src/db_utils.py
├── seed.py              Entry point helper — seeds classification_statuses on startup
├── routes/
│   ├── health.py        Route — GET /health
│   └── classify.py      Route — POST /classify, GET /classifications/*
├── controllers/
│   ├── classify.py      Controller — job submission and background execution
│   ├── bootstrap.py     Controller — corpus bootstrap pipeline orchestration
│   └── promote.py       Controller — nightly deferred corpus promotion job
├── models/
│   ├── jobs.py           Repository — classification_jobs, classifications, deferred_promotions;
│   │                                  cursor encode/decode delegated to shared/src/cursor_utils.py
│   ├── claims.py         Repository — claims
│   └── clusters.py       Repository — topic_clusters, corpus_centroids (incl. EWMA update,
│                                       get_corpus_centroids_bulk)
└── historical_ingestion/
    ├── schema.py         HistoricalDocument dataclass — common shape for all adapters
    ├── pipeline.py       Orchestrator — fetch, deduplicate, embed, upsert to Qdrant
    └── adapters/
        ├── base.py       AbstractHistoricalAdapter — fetch() interface
        ├── gdelt.py      GDELT 2.0 Doc API adapter
        └── arxiv.py      arXiv Atom feed adapter
```

Dependencies flow one way: `__main__` → `app` → `routes` → `controllers` → `models` → `db`.
`db.py` delegates its public API to `shared/src/db_utils.py`; cursor utilities in
`models/jobs.py` come from `shared/src/cursor_utils.py`.
`historical_ingestion` is a self-contained package; `pipeline.py` imports only adapters,
schema, and infrastructure (openai, qdrant-client) — no Postgres dependency.

## Bootstrap Pipeline

Invoked via `python -m src bootstrap --domain <slug> [--days-back 180] [--k 8]`.

1. **Fetch** — paginates `GET /runs?domain=<slug>&status=completed` then `GET /runs/{id}/articles` from `news-retrieval`; deduplicates by URL; skips articles with no body.
2. **Embed** — batches of 50 articles sent to OpenRouter (`openai/text-embedding-3-large`, 3072 dimensions). Bodies are truncated to 30,000 characters to stay within the model's 8,191-token limit. Point IDs are deterministic `uuid5(NAMESPACE_URL, url)` so re-runs skip already-embedded documents.
3. **Cluster** — all vectors scrolled from Qdrant; `MiniBatchKMeans(n_clusters=k)` run locally.
4. **Persist** — one Qdrant collection per cluster (`corpus_{domain}_{i}`); `topic_clusters` and `corpus_centroids` rows upserted to Postgres.

## Feature Extraction Pipeline

Runs as the background task for each `/classify` job (`run_classification_stub()` in `controllers/classify.py`).

For each article in the job:

1. **MinHash LSH dedup** — tokenises the body, builds a `MinHashLSH` index (threshold = 0.85, 128 permutations); near-duplicate articles are skipped and logged.
2. **Language filter** — `langdetect.detect()`; non-English articles are skipped and logged with their detected language code.
3. **Article embedding** — batch of 50 bodies sent to OpenRouter (`EMBEDDING_MODEL`, default `text-embedding-3-large`, 3072 dims); upserted to Qdrant `articles` collection with payload `{url, domain, published_date, label: null}`.
4. **Placeholder classification row** — `classifications` row inserted with `label='Noise'` and `composite_score=0.0`; CON-138 will UPDATE these with actual scores.
5. **Claim extraction** — LLM prompt (model: `OPENROUTER_MODEL`) returns 3–5 factual claims as a JSON array; malformed JSON falls back to no claims with a warning log.
6. **Claim embedding** — each claim embedded with `CLAIM_EMBEDDING_MODEL` (default `openai/text-embedding-3-small`, 1536 dims); upserted to Qdrant `claims` collection.
7. **Claim storage** — `claims` Postgres rows inserted with `claim_text`, `claim_embedding_id` (Qdrant UUID), and `embedding_model`.

All steps emit Langfuse spans when `LANGFUSE_PUBLIC_KEY` is set; tracing is silently disabled if absent.

## EWMA Centroid Update

After every classification, the article embedding updates the EWMA centroid for its assigned cluster (implemented by CON-138):

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

## Historical Ingestion Pipeline

Invoked via `python -m src historical-ingest --adapter <gdelt|arxiv> --query <text> --from YYYY-MM-DD --to YYYY-MM-DD [--collection <name>] [--dry-run]`.

Adds historical documents (news articles or research papers) directly to a Qdrant
collection with no Postgres involvement. Used to widen corpus coverage beyond what
`news-retrieval` provides.

1. **Fetch** — delegates to the selected adapter (GDELT or arXiv).
   - **GDELT**: queries the GDELT 2.0 Doc API (up to 250 results per call); fetches article body via Trafilatura; skips articles where body extraction fails.
   - **arXiv**: queries the arXiv Atom feed API, paginates in batches of 100, uses paper abstract as body.
2. **Deduplicate** — computes `uuid5(NAMESPACE_URL, url)` for each document; checks Qdrant for existing point IDs; skips documents already present.
3. **Embed** — batches of 50 bodies sent to OpenRouter (`text-embedding-3-large`, truncated to 30,000 chars).
4. **Upsert** — stores each point with payload `{url, source_adapter, published_date, label: null}`.

**Resumability**: deterministic point IDs mean interrupted runs are safe to restart — already-upserted documents are silently skipped.

**Adding a new adapter**: create `adapters/new_source.py` implementing `AbstractHistoricalAdapter.fetch()`, then add it to the `adapter_map` dict in `__main__.py`. No other files change.

## Vector Store

**Collections:**

| Collection | Contents | Vector size | Created by |
|------------|----------|-------------|------------|
| `bootstrap_{domain}` | All article embeddings for a domain (staging) | 3072 | `bootstrap` CLI |
| `corpus_{domain}_{i}` | Documents assigned to cluster `i` | 3072 | `bootstrap` CLI |
| `historical_{adapter}` | Historical documents from GDELT or arXiv | 3072 | `historical-ingest` CLI |
| `articles` | Live articles submitted via `/classify` | 3072 | Feature extraction pipeline |
| `claims` | Extracted claim embeddings linked to parent articles | 1536 | Feature extraction pipeline |

**Distance metric:** Cosine for all collections.

## Database Schema

| Table | Key columns |
|-------|-------------|
| `topic_clusters` | `id`, `slug`, `centroid_qdrant_collection`, `alpha` |
| `corpus_centroids` | `cluster_id`, `centroid_vector REAL[]`, `document_count`, `embedding_model` |
| `classification_jobs` | `id`, `run_id`, `status`, `article_count`, `callback_url` |
| `classifications` | `id`, `job_id`, `article_url`, `label`, `composite_score`, `article_embedding REAL[]`, `cluster_id` |
| `deferred_promotions` | `id`, `classification_id`, `promote_at`, `promoted_at`, `final_label` |
| `claims` | `id`, `classification_id`, `claim_text`, `claim_embedding_id`, `embedding_model` |

## HTTP API

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | None | Liveness check — Postgres, Qdrant, auth-service |
| `POST` | `/classify` | Bearer | Submit a classification job (202 Accepted) |
| `GET` | `/classifications/{job_id}` | Bearer | Job status and aggregate stats |
| `GET` | `/classifications/{job_id}/results` | Bearer | Paginated per-article results |

## Testing

Integration tests require `postgres-signal-test` (port 5435) to be running. Qdrant is not needed.

```bash
# From the repo root
docker compose up postgres-signal-test -d

# Run locally (conftest connects to localhost:5435)
pip install -r signal-detection/requirements-test.txt
pytest signal-detection/tests/

# Or inside Docker (override the DB host for the container network)
docker build -t signal-detection-test --target test signal-detection/
docker run --rm --network ocn_ocn-internal \
  --env-file .env \
  -e POSTGRES_HOST=postgres-signal-test \
  -e POSTGRES_PORT=5432 \
  signal-detection-test pytest tests/
```

| Module | Coverage |
|--------|----------|
| `test_smoke.py` | Health endpoint, app startup |
| `test_classify.py` | POST /classify, GET /classifications/* |
