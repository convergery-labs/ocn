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

> **Docker build context**: the Dockerfile must be built from the repo root so
> that `shared/src/` is available. `docker compose` handles this automatically
> via the `context: .` setting in `docker-compose.yml`. When building manually,
> run `docker build -f signal-detection/Dockerfile .` from the repo root.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SIGNAL_POSTGRES_PASSWORD` | Yes | — | PostgreSQL password |
| `SIGNAL_POSTGRES_DB` | No | `signal-detection` | PostgreSQL database name |
| `SIGNAL_POSTGRES_USER` | No | `signal-detection` | PostgreSQL user |
| `SIGNAL_POSTGRES_HOST` | No | `localhost` | PostgreSQL host |
| `QDRANT_HOST` | No | `qdrant` | Qdrant hostname |
| `QDRANT_PORT` | No | `6333` | Qdrant port |
| `NEWS_RETRIEVAL_URL` | Yes | — | news-retrieval base URL for run triggering, polling, and article fetching |
| `NEWS_RETRIEVAL_SERVICE_CALLER` | No | pre-encoded admin identity | Base64-encoded `x-ocn-caller` JSON used for service-to-service calls to news-retrieval |
| `PIPELINE_POLL_TIMEOUT_SECS` | No | `600` | Max seconds to wait for a news-retrieval run to complete before failing |
| `AUTH_SERVICE_URL` | Yes | — | auth-service base URL for token validation |
| `OPENROUTER_API_KEY` | Yes | — | OpenRouter API key for embeddings and LLM calls |
| `OPENROUTER_MODEL` | No | `openai/gpt-4o-mini` | LLM model used for claim extraction |
| `EMBEDDING_MODEL` | No | `openai/text-embedding-3-large` | Article embedding model (OpenRouter prefix format) |
| `CLAIM_EMBEDDING_MODEL` | No | `openai/text-embedding-3-small` | Claim embedding model (1536 dims; claims are short, compared only to other claims) |
| `SIGNAL_THRESHOLD` | No | `0.5` | Cosine similarity threshold used by the deferred promotion job |
| `LANGFUSE_PUBLIC_KEY` | No | — | Langfuse public key; tracing disabled if absent |
| `LANGFUSE_SECRET_KEY` | No | — | Langfuse secret key |
| `LANGFUSE_HOST` | No | `https://cloud.langfuse.com` | Langfuse host |

## Bootstrap CLI

Seeds the Qdrant corpus before the service can classify articles. Idempotent — re-runs skip already-embedded documents and articles whose claims are already stored.

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

The command:
1. Fetches completed runs from `news-retrieval` and embeds article bodies via OpenRouter (`text-embedding-3-large`, truncated to 30,000 characters).
2. Extracts 3–5 factual claims per article via LLM (`OPENROUTER_MODEL`) and stores claim embeddings in the Qdrant `claims` collection (`text-embedding-3-small`, 1536 dims). This seeds claim novelty scoring so the first classification run produces results across all three labels rather than defaulting to cold-start scores. Failures are logged and skipped without aborting bootstrap.
3. Clusters article embeddings with MiniBatchKMeans and writes `topic_clusters` + `corpus_centroids` rows to Postgres with one Qdrant collection per cluster.

## Historical Ingest CLI

Seeds the Qdrant corpus with historical documents from external sources. Qdrant-only — no Postgres involvement. Idempotent: re-runs skip already-upserted documents.

```bash
docker compose run --rm signal-detection python -m src historical-ingest \
    --adapter gdelt \
    --query "large language model" \
    --from 2023-01-01 \
    --to 2023-03-31

docker compose run --rm signal-detection python -m src historical-ingest \
    --adapter arxiv \
    --query "attention mechanism" \
    --from 2017-06-01 \
    --to 2017-12-31 \
    --dry-run
```

| Option | Default | Description |
|--------|---------|-------------|
| `--adapter` | required | `gdelt` (news articles) or `arxiv` (research papers) |
| `--query` | required | Keyword or phrase to search for |
| `--from` | required | Inclusive start date (`YYYY-MM-DD`) |
| `--to` | required | Inclusive end date (`YYYY-MM-DD`) |
| `--collection` | `historical_{adapter}` | Target Qdrant collection name |
| `--dry-run` | `false` | Report document count without embedding |

**GDELT**: returns up to 250 articles per call (API hard limit). Narrow the date range for more targeted results. Article bodies are fetched via Trafilatura; articles with no extractable body are skipped.

**arXiv**: paginates through all matching papers in batches of 100. Uses the paper abstract as the document body.

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
| `POST` | `/run` | Unified fetch-and-classify pipeline (returns 202) |
| `POST` | `/classify` | Submit a classification job directly (returns 202) |
| `GET` | `/classifications/{job_id}` | Job status and aggregate stats |
| `GET` | `/classifications/{job_id}/results` | Paginated per-article results |

### POST /run

Triggers the full end-to-end pipeline: fetches articles from news-retrieval, then classifies them. Returns a `job_id` immediately (202); the pipeline runs in the background. Use `GET /classifications/{job_id}` to poll for completion.

`domain` must be a slug registered in news-retrieval. The request is rejected with 422 if the slug is unknown.

```json
{
  "domain": "ai_news",
  "days_back": 7,
  "max_articles": 200,
  "focus": "optional topic narrowing instruction",
  "force": false,
  "callback_url": "https://example.com/webhook"
}
```

Returns `{"job_id": 1, "status": "processing"}`. On completion, POSTs
`{"job_id": 1, "status": "completed"}` to `callback_url` if provided.

### POST /classify

Accepts either a `run_id` (fetches articles from news-retrieval) or an inline
`articles` list — not both. `domain` is required and must be a slug registered
in news-retrieval (i.e. appears in `GET /domains`). The service validates this
before creating a job and returns 422 if the slug is unknown — classification
cannot proceed without a bootstrapped corpus to compare articles against.

```json
{
  "run_id": 42,
  "domain": "ai_news",
  "callback_url": "https://example.com/webhook"
}
```

```json
{
  "articles": [
    {"url": "...", "title": "...", "body": "...", "source": "...", "published": "..."}
  ],
  "domain": "ai_news",
  "callback_url": "https://example.com/webhook"
}
```

Returns `{"job_id": 1, "status": "processing"}`. On completion, POSTs
`{"job_id": 1, "status": "completed"}` to `callback_url` if provided.

### GET /classifications/{job_id}/results

Supports cursor-based pagination via `limit` (1–100, default 20) and `cursor`
query parameters.

## Plausibility Filter

After scoring, articles with `composite_score > PLAUSIBILITY_THRESHOLD` (default 0.40) are passed
through an LLM plausibility filter before the final label is stored. This guards against false
positives: conspiracy theories, speculative extrapolation, and low-credibility sources can score
high on novelty metrics without being genuinely signal-worthy.

**LLM call:** A single Claude Sonnet call via OpenRouter (`PLAUSIBILITY_MODEL`) receives the article
title, body (truncated to ~2,000 tokens), and composite score context. It returns structured JSON:

```json
{
  "plausibility_score": 0.0–1.0,
  "flags": ["conspiracy_framing", "no_credible_mechanism",
            "low_credibility_source", "speculative_extrapolation"],
  "reasoning": "brief explanation"
}
```

**Downgrade logic:**
- `plausibility_score < 0.30` AND label is `Signal` → downgrade to `Weak Signal`;
  set `flagged_for_review = true`
- `plausibility_score < 0.30` AND label is `Weak Signal` → label unchanged;
  set `flagged_for_review = true`
- All other cases → label and flag unchanged
- `Noise` articles skip the filter entirely (all plausibility fields remain `null`)

**Stored fields** on the `classifications` row:
`plausibility_score`, `plausibility_flags` (JSONB), `plausibility_reasoning` (text),
`flagged_for_review` (boolean, default `false`)

**Cost guard:** Each call logs token count to Langfuse in a `plausibility` span. A warning is
emitted if a single call exceeds `PLAUSIBILITY_TOKEN_WARN_THRESHOLD` tokens (default 4096).

**On LLM failure:** JSON parse errors or API exceptions are logged; the filter is skipped and the
label is not downgraded (plausibility fields remain `null`, `flagged_for_review` remains `false`).

| Variable | Default | Description |
|----------|---------|-------------|
| `PLAUSIBILITY_THRESHOLD` | `0.40` | Minimum composite score to trigger filter |
| `PLAUSIBILITY_DOWNGRADE_THRESHOLD` | `0.30` | Plausibility score below which downgrade applies |
| `PLAUSIBILITY_MODEL` | `anthropic/claude-sonnet-4-5` | OpenRouter model for plausibility call |
| `PLAUSIBILITY_TOKEN_WARN_THRESHOLD` | `4096` | Warn if token count per call exceeds this |

## Concept Taxonomy & NER Pipeline

Each classified article has its text processed by a spaCy `en_core_web_lg` NER
pipeline that extracts named entities and noun chunks, maps them against
`src/taxonomy_mappings.json`, and stores the matched concept slugs as a JSONB
array on the `classifications` row, and feeds the bridge score (Sub-score B).

**Bridge score (Sub-score B):** After concept extraction, all canonical concept
pairs are upserted into the `concept_cooccurrences` Postgres table. The bridge
score rewards articles that connect rarely co-occurring concept pairs:
`mean(1 / (1 + log(1 + count)))` across all pairs. When ≥ 2 concepts are
present the composite formula switches to Phase 4 weights
(`0.25 * A + 0.30 * B + 0.45 * C`); articles with fewer than 2 concepts fall
back to Phase 3 weights (`0.40 * A + 0.60 * C`).

The taxonomy contains 40 v1 concept slugs in 8 domain groups (e.g. `ai-core`,
`science`, `governance`, `finance`). `taxonomy_mappings.json` maps ≥150 keyword
patterns to those slugs and can be edited without code changes.

The `en_core_web_lg` model is downloaded automatically during the Docker image
build. To install it locally for testing:

```bash
pip install "spacy>=3.7,<4"
python -m spacy download en_core_web_lg
```

## Testing

Tests connect to `postgres-signal-test` on `localhost:5435`. Qdrant is not needed.

```bash
# From the repo root
docker compose up postgres-signal-test -d
pip install -r signal-detection/requirements-test.txt
pytest signal-detection/tests/
```

Test modules:

| Module | Coverage |
|--------|----------|
| `test_smoke.py` | Health endpoint, app startup |
| `test_classify.py` | POST /classify and GET /classifications/* endpoints |
| `test_ner.py` | `extract_concepts` — multi-concept match, zero-match, deduplication |
