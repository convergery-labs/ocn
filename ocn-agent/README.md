# ocn-agent

Part of the [ocn monorepo](../README.md). See root README for full system setup.

LangGraph-driven agent that accepts a natural-language prompt, resolves it to a
domain, fetches relevant articles from the internal `news-retrieval` service,
categorises them into verticals, and returns per-category and roll-up summaries.

Internal only — no public ALB endpoint.

## Stack

- **Server**: FastAPI + uvicorn
- **Agent**: LangGraph `StateGraph`
- **Upstream**: `news-retrieval` (async `httpx`)

## Quick start

```bash
cp .env.example .env
# Fill in NEWS_RETRIEVAL_API_KEY

docker compose up ocn-agent
```

> **Note:** The `ocn-agent` Docker image must be built from the **repo root**
> (not from `ocn-agent/`), because the Dockerfile uses `context: .` in
> `docker-compose.yml`. `docker compose` handles this automatically.

The service listens on port **8003**. Interactive docs at
`http://localhost:8003/docs`.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `NEWS_RETRIEVAL_URL` | Yes | Base URL of the internal news-retrieval service (e.g. `http://news-retrieval:8000`) |
| `NEWS_RETRIEVAL_API_KEY` | Yes | API key sent as `x-ocn-caller` header to news-retrieval |

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/agent/query` | Submit a natural-language query; returns a structured result with categorised and summarised articles |
| `POST` | `/agent/categorise` | Categorise a pre-fetched article set into domain verticals |
| `GET` | `/health` | Health check — returns 200 when env vars are configured, 503 otherwise |

### POST /agent/query

Accepts a natural-language prompt and runs the full LangGraph pipeline:
parse → domain resolution → news fetch → categorisation → summarisation.

If the prompt is ambiguous the agent returns a clarification request instead
of running the pipeline.

### GET /health

```bash
curl http://localhost:8003/health
# {"status":"ok","checks":{"news_retrieval_url_configured":true,"news_retrieval_api_key_configured":true}}
```

Returns `503` with `"status": "degraded"` if any required env var is missing.
