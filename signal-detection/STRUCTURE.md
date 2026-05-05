# Structure

## Root

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build: `base` (production), `dev` (hot-reload), `test` (pytest). Build context is the repo root (`docker build -f signal-detection/Dockerfile .`); copies `signal-detection/src/`, `signal-detection/requirements.txt`, and `shared/src/` into the image. |
| `requirements.txt` | Production dependencies |
| `requirements-test.txt` | Test-only dependencies (pytest, httpx, psycopg2) |
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
├── seed.py              Entry point helper — seeds classification_statuses and
│                                         concept_taxonomy on startup
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
│   ├── cooccurrences.py  Repository — concept_cooccurrences; upsert_cooccurrences(),
│   │                                  get_cooccurrence_counts()
│   └── clusters.py       Repository — topic_clusters, corpus_centroids (incl. EWMA update,
│                                       get_corpus_centroids_bulk, get_clusters_for_domain)
├── taxonomy_mappings.json  Config — keyword → concept-slug mappings; human-editable
│                                   without code changes (≥150 entries, covers all 40 slugs)
├── pipeline/
│   └── ner.py            Infrastructure — spaCy en_core_web_lg NER pipeline;
│                                          extract_concepts(text) → sorted list of concept
│                                          slugs; singleton model load; safe (never raises)
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

## Agent Loop (Classification Pipeline)

Runs as the background task for each `/classify` job (`run_agent_loop()` in `controllers/classify.py`). Two phases run in sequence:

### Phase 1 — Feature Extraction (`_run_feature_extraction`)

1. **MinHash LSH dedup** — tokenises the body, builds a `MinHashLSH` index (threshold = 0.85, 128 permutations); near-duplicate articles are skipped and logged.
2. **Language filter** — `langdetect.detect()`; non-English articles are skipped and logged with their detected language code.
3. **Article embedding** — batch of 50 bodies sent to OpenRouter (`EMBEDDING_MODEL`, default `text-embedding-3-large`, 3072 dims); upserted to Qdrant `articles` collection with payload `{url, domain, published_date, label: null}`.
4. **Placeholder classification row** — `classifications` row inserted with `label='Noise'` and `composite_score=0.0`; updated by Phase 2.
5. **Claim extraction** — LLM prompt (model: `OPENROUTER_MODEL`) returns 3–5 factual claims as a JSON array; malformed JSON falls back to no claims with a warning log.
6. **Claim embedding** — each claim embedded with `CLAIM_EMBEDDING_MODEL` (default `openai/text-embedding-3-small`, 1536 dims); upserted to Qdrant `claims` collection.
7. **Claim storage** — `claims` Postgres rows inserted with `claim_text`, `claim_embedding_id` (Qdrant UUID), and `embedding_model`.
8. **NER concept extraction** — spaCy `en_core_web_lg` extracts named entities and noun chunks from `title + body`; matched against `taxonomy_mappings.json` keyword patterns; deduplicated concept slugs written to `classifications.concepts` (JSONB). Articles with no matches log a warning and store an empty array.

All steps emit Langfuse spans when `LANGFUSE_PUBLIC_KEY` is set; tracing is silently disabled if absent.

### Phase 2 — Scoring (`_run_scoring_phase`)

For each article classified in Phase 1:

1. **Cluster assignment** (`_assign_cluster`) — cosine similarity between the article embedding and each cluster centroid in `corpus_centroids`; nearest cluster wins. Low-confidence flag raised when similarity < `MIN_CLUSTER_SIMILARITY` (default 0.3). Cold-start default score used when no centroid vectors exist.
2. **Sub-score A — trajectory deviation** — `1 - cosine_similarity`, normalised to [0, 1].
3. **Sub-score B — bridge score** (`_compute_bridge_score`) — reads `concepts` JSONB from the classification row; upserts all canonical concept pairs into `concept_cooccurrences`; computes `mean(1 / (1 + log(1 + count)))` across all pairs. Returns `null` when fewer than 2 concepts are extracted (logged as `bridge_score_unavailable`).
4. **Sub-score C — claim novelty** (`_compute_claim_novelty`) — for each extracted claim, Qdrant `search` against the `claims` collection (k=10) excluding the article's own claims; score = mean cosine distance. `COLD_START_CLAIM_SCORE` (default 0.5) used when the claim store is empty.
5. **Composite score** (`_compute_composite`) — Phase 4 (bridge available): `0.25 * A + 0.30 * B + 0.45 * C`; Phase 3 fallback (bridge=null): `0.40 * A + 0.60 * C`. All weights env-configurable (`W_TRAJECTORY`, `W_CLAIM_NOVELTY`, `W_TRAJECTORY_P4`, `W_BRIDGE`, `W_CLAIM_NOVELTY_P4`).
6. **Label** (`_assign_label`) — High Signal ≥ 0.70, Weak Signal 0.40–0.70, Noise < 0.40. Thresholds env-configurable (`SIGNAL_THRESHOLD`, `WEAK_SIGNAL_THRESHOLD`).
7. **DB update** — `classifications` row updated with label, scores, and `cluster_id`.
8. **Deferred promotion** — Signal articles inserted into `deferred_promotions` with `promote_at = now() + 30 days`.

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
| `classifications` | `id`, `job_id`, `article_url`, `source`, `label`, `composite_score`, `trajectory_score`, `bridge_score`, `claim_novelty_score`, `article_embedding REAL[]`, `cluster_id`, `concepts JSONB` |
| `concept_cooccurrences` | `concept_a`, `concept_b` (PRIMARY KEY pair, a < b), `co_occurrence_count`, `last_updated_at` |
| `deferred_promotions` | `id`, `classification_id`, `promote_at`, `promoted_at`, `final_label` |
| `claims` | `id`, `classification_id`, `claim_text`, `claim_embedding_id`, `embedding_model` |
| `concept_taxonomy` | `id`, `slug`, `display_name`, `domain_group` — 40 v1 entries seeded at startup |

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
| `test_feature_extraction.py` | MinHash dedup, language filter, article embedding, claim extraction, claim embedding + Postgres storage, Langfuse tracing |
| `test_scoring.py` | `_assign_cluster`, `_compute_claim_novelty`, `_compute_bridge_score`, `_compute_composite` (Phase 3 + 4), `_assign_label`, `_cosine_similarity` |
| `test_ner.py` | `extract_concepts` — multi-concept match, zero-match, deduplication |
