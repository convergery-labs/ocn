# Structure

## Root

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build: `base` (production), `dev` (hot-reload), `test` (pytest). Build context is the repo root; copies `signal-detection-agent/src/`, `signal-detection-agent/requirements.txt`, `shared/src/`, and `signal-detection-agent/prompts/` into the image. |
| `requirements.txt` | Production dependencies |
| `requirements-test.txt` | Test-only dependencies |
| `pyproject.toml` | pytest configuration (`asyncio_mode=auto`) |
| `prompts/ai_universe_signal_classifier_v1.txt` | Base-pass LLM system prompt — 11 AI-universe categories + "none" (noise only), signal/weak_signal/noise scoring bands, tie-breaker rules, 15 labelled examples |
| `prompts/ai_universe_signal_classifier_v2_refine.txt` | Second-pass (STORM-style) LLM system prompt — refinement rules, novelty/confidence definitions with score bands, 3 labelled examples |

## App Layers

```
src/
├── __main__.py          Entry point — Click group: serve
├── app.py               App factory — assembles FastAPI, registers routers
├── auth.py              Infrastructure — x-ocn-caller header extraction
├── db.py                Infrastructure — _new_connection(), init_db() (creates
│                                         agent_jobs + agent_classifications);
│                                         re-exports get_db/transaction/DuplicateError
│                                         from shared/src/db_utils.py
├── seed.py              Entry point helper — seeds agent_job_statuses on startup
├── config.py            Configuration — OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL,
│                                        NEWS_RETRIEVAL_URL, PIPELINE_POLL_TIMEOUT_SECS,
│                                        DEFAULT_PROMPT, DEFAULT_PROMPT_V2 paths,
│                                        WEB_SEARCH_PROVIDER, WEB_SEARCH_API_KEY
├── routes/
│   ├── health.py        Route — GET /health (Postgres liveness)
│   ├── run.py           Route — POST /run → 202 {job_id, cached:false} or 200 {job_id, cached:true}
│   └── jobs.py          Route — GET /jobs, GET /jobs/{id}, GET /jobs/{id}/results
├── controllers/
│   └── run.py           Controller — submit_run() resolves news_run_id + checks cache
│                                     (returns existing job on hit); run_agent_pipeline()
│                                     background task: get_run_articles → classify each
│                                     article → insert_classification → update status
├── models/
│   └── jobs.py          Repository — agent_jobs + agent_classifications;
│                                     cursor pagination via shared/src/cursor_utils.py
├── pipeline/
│   ├── classifier.py    LLM classifier — classify_article_two_stage() (STORM two-pass),
│   │                                     classify_article() (base pass),
│   │                                     validate_classification_v2() (novelty/confidence/
│   │                                       pre_verification_score/verification_qa validation),
│   │                                     validate_classification() (base-pass validation),
│   │                                     apply_verification_adjustments() (QA score → final score + trace),
│   │                                     build_user_prompt_v2(), build_user_prompt(),
│   │                                     has_usable_body(); OpenAI-compatible API (OPENAI_BASE_URL)
│   └── category_candidates.py  PARKED — embedding cosine-similarity pre-step to
│                                         shortlist top-k categories per article;
│                                         not called in v1; re-enable via category_hints
│                                         param in classify_article() if needed
└── adapters/
    ├── news_client.py   Infrastructure — async HTTP client for news-retrieval:
    │                                     trigger_run(), fetch_latest_run(),
    │                                     poll_run_until_done(), get_run_articles()
    └── web_search.py    Infrastructure — urllib search client for entity context:
                                          search_entity_context(); providers: duckduckgo
                                          (default, free), tavily, brave
```

Dependencies flow one way: `__main__` → `app` → `routes` → `controllers` → `models` → `db`.
`pipeline/` and `adapters/` are called by `controllers/run.py` only.

## Pipeline Flow

`POST /run {domain, run_id?, force?}`:

1. Resolve `news_run_id`: if `run_id` given → poll until done; else if `use_latest_run` → reuse latest; else `trigger_run + poll`
2. Cache check (unless `force=true`): if a completed job already exists for this `news_run_id` → return 200 `{job_id, cached:true}` immediately
3. Create new `agent_jobs` row → return 202 `{job_id, cached:false}`

Background task (`run_agent_pipeline`):

4. `get_run_articles(run_id)` — paginates `GET /runs/{id}/articles?include_body=true`
5. Filter articles with a usable body (`has_usable_body`)
6. Build `batch_context` — list of `{title, url}` for all usable articles in this run (passed read-only to all concurrent classifiers)
7. For each article: `classify_article_two_stage()` — two-stage STORM pipeline:
   - **Base pass**: `classify_article()` → LLM (v1 prompt) → `validate_classification()`
   - **If noise**: final = base; second-pass fields = null (skip second pass)
   - **If signal/weak_signal**: gather context concurrently via `ThreadPoolExecutor`:
     - DB: `get_recent_entity_classifications()` — exact lowercased array-overlap on `entity_names_normalized`, last 90 days
     - Web: `search_entity_context()` — queries built from entity name + `signal_reason` (first 60 chars); up to 2 queries, top-3 snippets, 5s timeout; 1.5s rate delay between queries for DuckDuckGo; returns [] on failure
   - **Second pass**: LLM (v2 prompt + article + base result + entity history + web snippets + batch_context, max_tokens=2000) → `validate_classification_v2()`
   - `apply_verification_adjustments()`: sums QA `score_adjustment` values → final score; injects score trace into `refinement_reason`
   - **If second pass fails**: fall back to base result with null second-pass fields
8. `insert_classification(job_id, article, result)` — persists to `agent_classifications`
9. `update_job_status(job_id, "completed")`

## HTTP API

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | None | Liveness — Postgres SELECT 1 |
| `POST` | `/run` | x-ocn-caller | Trigger pipeline; body: `{domain, run_id?, limit?, days_back?, use_latest_run?, force?}`; 202 `{job_id, cached:false}` or 200 `{job_id, cached:true}` if already completed |
| `GET` | `/jobs` | x-ocn-caller | Jobs, newest-first; cursor-paginated (`limit`, `cursor`) |
| `GET` | `/jobs/{id}` | x-ocn-caller | Single job status + stats |
| `GET` | `/jobs/{id}/results` | x-ocn-caller | Paginated `agent_classifications` for a job |

## Database

Tables live in the signal-detection Postgres DB with an `agent_` prefix (mirrors signal-detection's `classification_jobs` / `classifications` pattern):

| Table | Key columns |
|-------|-------------|
| `agent_job_statuses` | `status TEXT PK` — reference values: pending, running, completed, failed |
| `agent_jobs` | `id SERIAL PK`, `news_run_id`, `domain`, `status FK`, `article_count`, `created_at`, `completed_at` |
| `agent_classifications` | `id SERIAL PK`, `job_id FK`, `article_id`, `url`, `title`, `signal_detection`, `signal_score`, `signal_reason`, `materiality`, `category`, `entities_json TEXT`, `entity_names_normalized TEXT[]`, `stored_at`, `base_signal_detection`, `base_signal_score`, `novelty`, `novelty_basis`, `confidence`, `confidence_basis`, `refinement_reason`, `pre_verification_score`, `verification_qa JSONB` |

`url` and `title` are lightweight display references only — full article content stays in news-retrieval.
Second-pass columns (`base_*`, `novelty*`, `confidence*`, `refinement_reason`, `pre_verification_score`, `verification_qa`) are NULL for noise articles and for rows classified before the two-stage pipeline (backward-compatible).
`entity_names_normalized` is a lowercased TEXT[] for exact array-overlap entity matching; GIN-indexed. NULL/empty on pre-normalisation rows (backfilled on startup).

## LLM Output Schema

| Field | Values | Notes |
|-------|--------|-------|
| `signal_detection` | `signal` \| `weak_signal` \| `noise` | Final label (second pass if ran, else base) |
| `signal_score` | 0.00–1.00 (noise ≤ 0.40, weak_signal 0.41–0.59, signal ≥ 0.60) | Final score |
| `signal_reason` | ~30-word explanation naming specific entities | |
| `materiality` | `high` \| `medium` \| `low` \| `none` (none only for noise) | |
| `category` | one of 11 AI-universe categories — always a real category, including for noise | |
| `entities` | `[{name, type}]` — 1–5 named entities | |
| `base_signal_detection` | `signal` \| `weak_signal` \| `noise` | First-pass label |
| `base_signal_score` | 0.00–1.00 | First-pass score |
| `novelty` | `step_change` \| `meaningful_update` \| `incremental_update` \| `repeated_coverage` or null | null when second pass skipped (noise) |
| `novelty_basis` | ~20-word string or null | which novelty branch and what evidence |
| `confidence` | `high` \| `medium` \| `low` or null | null when second pass skipped (noise) |
| `confidence_basis` | ~20-word string or null | what evidence drove the confidence label |
| `refinement_reason` | 5-6 line string or null | context available → decision → evidence → novelty branch → confidence basis → edge case; score trace appended by code |
| `pre_verification_score` | 0.00–1.00 or null | Stage 2 score before QA adjustments; null when second pass skipped |
| `verification_qa` | list of 2–3 objects or null | per-question score adjustments: `question`, `answer`, `evidence` (verbatim quote + URL if from web), `score_adjustment` |

## Testing

```bash
docker compose up postgres-signal signal-detection-agent --build
curl http://localhost:8003/health
```
