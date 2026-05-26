# signal-herald — Structure

```
signal-herald/
├── Dockerfile            multi-stage: base + dev (--reload)
├── requirements.txt      FastAPI, uvicorn, httpx, openai, click, pydantic
└── src/
    ├── __main__.py       CLI entry: `serve` (FastAPI) and `run` (one-shot digest)
    ├── app.py            FastAPI factory — mounts health, a2a, webhooks routers
    ├── config.py         Env var loading, 11 category list, recipient list, poll config
    ├── adapters/
    │   ├── llm_client.py          OpenRouter summaries via OpenAI-compatible SDK
    │   ├── signal_agent_client.py HTTP client for signal-detection-agent (trigger, poll, paginate results)
    │   └── smtp_sender.py         Gmail TLS email dispatch — renders HTML with tier/materiality badges
    ├── controllers/
    │   └── digest.py              Pipeline orchestration: dedup check → trigger → poll → summarise → send
    └── routes/
        ├── a2a.py        GET /.well-known/agent.json + POST / JSON-RPC dispatcher
        ├── health.py     GET /health
        └── webhooks.py   POST /webhooks/signal-agent (stub)
```

## Layer Responsibilities

| Layer | Responsibility |
|-------|---------------|
| `routes/` | HTTP boundary — parse requests, delegate to controllers, return responses |
| `controllers/` | Pipeline logic — orchestrate adapters, enforce dedup, manage async tasks |
| `adapters/` | External I/O — signal-agent HTTP, OpenRouter LLM, SMTP |
| `config.py` | Single source of truth for env vars, categories, recipients, timeouts |
