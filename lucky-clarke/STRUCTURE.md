# Structure

## Root

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build: `base` (production), `dev` (hot-reload), `test` (pytest). Build context is the repo root. |
| `requirements.txt` | Production dependencies |
| `requirements-test.txt` | Test-only dependencies |
| `pyproject.toml` | pytest configuration |

## App Layers

```
src/
├── __main__.py       Entry point — Click group: serve, run
├── app.py            App factory — creates FastAPI, registers routers
├── config.py         Configuration — CATEGORIES, EMAIL_RECIPIENTS, env vars
├── routes/
│   ├── health.py     Route — GET /health
│   ├── a2a.py        Route — GET /.well-known/agent.json (Agent Card);
│   │                          POST / (JSON-RPC 2.0 dispatcher, tasks/send)
│   └── webhooks.py   Route — POST /webhook/news-retrieval,
│                              POST /webhook/signal-detection
├── controllers/
│   └── digest.py     Controller — full pipeline: check freshness →
│                                   trigger retrieval → trigger classification →
│                                   fetch results → categorise → summarise → email
└── adapters/
    ├── signal_client.py  Infrastructure — httpx client for signal-detection:
    │                                      get_latest_job(), trigger_run(),
    │                                      poll_job_until_done(), get_job_results()
    ├── llm_client.py     Infrastructure — OpenRouter via openai SDK:
    │                                      categorise_articles(), summarise_category()
    └── smtp_sender.py    Infrastructure — smtplib SMTP: send_digest()
```

Dependencies flow one way: `__main__` → `app` → `routes` → `controllers` → `adapters`.

## Execution Modes

| Mode | Command | Invoked by |
|------|---------|-----------|
| **serve** | `python -m src serve` | ECS long-running service (desired_count=1) |
| **run** | `python -m src run` | EventBridge cron → ECS one-shot task (7 AM UTC daily) |

## HTTP API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `GET` | `/.well-known/agent.json` | A2A Agent Card |
| `POST` | `/` | JSON-RPC 2.0 — `tasks/send` triggers digest pipeline (async) |
| `POST` | `/webhook/news-retrieval` | Callback from news-retrieval on run completion |
| `POST` | `/webhook/signal-detection` | Callback from signal-detection on classification completion |

## Pipeline

```
run_digest_polling() / run_digest_async()
  └─ signal_client.get_latest_job()          # check if today's classification exists
       ├─ if fresh → skip to fetch results
       └─ if stale / missing:
            signal_client.trigger_run()       # POST /run (signal-detection calls
            signal_client.poll_job_until_done() # news-retrieval internally)
  └─ signal_client.get_job_results()          # paginate classifications (incl. titles)
  └─ llm_client.categorise_articles()         # batch LLM: assign to 12 categories
  └─ llm_client.summarise_category() × N      # one LLM call per non-empty category
  └─ ses_sender.send_digest()                 # send HTML email via AWS SES
```

## Testing

```bash
# From repo root
pip install -r lucky-clarke/requirements-test.txt
pytest lucky-clarke/tests/
```

No external services required — all HTTP clients and SES are mocked.
