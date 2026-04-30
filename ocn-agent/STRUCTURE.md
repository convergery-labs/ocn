# Structure

## Root

| Path | Description |
|------|-------------|
| `Dockerfile` | Builds a `python:3.12-slim` image; copies `src/` to `/app` and installs pip dependencies; no `shared/` dependency |
| `requirements.txt` | Production pip dependencies |
| `.env.example` | Template for required env vars |
| `README.md` | Project overview and quick-start instructions |
| `CLAUDE.md` | AI assistant instructions: overview, Jira board, structural guide, maintenance rules |
| `STRUCTURE.md` | This file |
| `src/__main__.py` | CLI entry point — `click` + `uvicorn.run`; no DB init or seed |
| `src/app.py` | FastAPI app factory: creates instance and registers routers |
| `src/state.py` | `AgentState` TypedDict shared across all graph nodes |
| `src/config.py` | Hardcoded domain config: `DOMAINS` dict keyed by slug (`ai_news`, `smart_money`), each with description and verticals list |
| `src/clients/news_retrieval.py` | `NewsRetrievalClient` — async `httpx.AsyncClient` targeting `NEWS_RETRIEVAL_URL`; injects `x-ocn-caller: <NEWS_RETRIEVAL_API_KEY>` on every request |
| `src/graph/__init__.py` | Re-exports the compiled `graph` object |
| `src/graph/graph.py` | `StateGraph` definition: all nodes and edges; conditional edge from `resolve_domain_and_params` to either the main pipeline or `return_clarification` |
| `src/routes/health.py` | `GET /health` — checks env var configuration |
| `src/routes/agent.py` | `POST /agent/query` and `POST /agent/categorise` stub routes |

## App layers

| Layer | File(s) | Responsibility |
|-------|---------|----------------|
| **Entry point** | `src/__main__.py` | CLI wiring (`click`), starts `uvicorn` |
| **App factory** | `src/app.py` | Creates `FastAPI` instance, registers routers |
| **Routes** | `src/routes/` | Thin HTTP adapters; one `APIRouter` per resource |
| **Graph** | `src/graph/` | LangGraph `StateGraph`; nodes + conditional routing |
| **State** | `src/state.py` | Shared `AgentState` TypedDict passed between nodes |
| **Config** | `src/config.py` | Static domain config; no DB |
| **Clients** | `src/clients/` | Async HTTP clients for upstream OCN services |

## HTTP API

| Endpoint | Description |
|----------|-------------|
| `POST /agent/query` | Submit a natural-language query; returns structured result (stub: 501) |
| `POST /agent/categorise` | Categorise a pre-fetched article set (stub: 501) |
| `GET /health` | Service health check |

## Graph topology

```
parse_prompt
  └─ resolve_domain_and_params
       ├─ [clarification_message set] → return_clarification  (terminal)
       └─ [otherwise]                → call_news_retrieval
                                          └─ categorise
                                               └─ summarise
                                                    └─ return_result  (terminal)
```

## AgentState fields

| Field | Type | Description |
|-------|------|-------------|
| `prompt` | `str` | Raw user prompt |
| `domain_slug` | `str \| None` | Resolved domain slug (e.g. `ai_news`) |
| `confidence` | `float \| None` | Model confidence in the domain resolution |
| `days_back` | `int \| None` | How many days back to fetch articles |
| `focus` | `str \| None` | Optional sub-topic focus instruction |
| `run_id` | `str \| None` | news-retrieval run ID after fetching |
| `articles` | `list[dict] \| None` | Articles returned by news-retrieval |
| `category_assignments` | `dict[str, str] \| None` | Article ID → vertical category mapping |
| `summaries` | `dict[str, str] \| None` | Per-category summaries |
| `roll_up_summary` | `str \| None` | Cross-category roll-up summary |
| `clarification_message` | `str \| None` | Message to return when the prompt is ambiguous |

## Domain config

Hardcoded in `src/config.py`. Each entry has:
- `slug` — unique identifier matching news-retrieval domain slugs
- `description` — human-readable description passed to the LLM
- `verticals` — list of vertical category strings used during categorisation

Current slugs: `ai_news`, `smart_money`.

## Dependencies

### Python packages

| Package | Purpose |
|---------|---------|
| `fastapi` | HTTP server framework |
| `uvicorn` | ASGI server |
| `pydantic` | Data validation |
| `click` | CLI entry point |
| `httpx` | Async HTTP client (news-retrieval) |
| `langgraph` | Agent graph orchestration |

### Runtime environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `NEWS_RETRIEVAL_URL` | Yes | Base URL of the internal news-retrieval service (e.g. `http://news-retrieval:8000`) |
| `NEWS_RETRIEVAL_API_KEY` | Yes | API key sent as `x-ocn-caller` header to news-retrieval |
