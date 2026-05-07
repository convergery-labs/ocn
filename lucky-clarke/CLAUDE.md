# lucky-clarke

Part of the [ocn monorepo](../CLAUDE.md).

## Overview

`lucky-clarke` is an A2A-compatible daily AI news digest agent (port 8005). It checks whether a fresh signal-detection classification exists for today, triggers the news-retrieval + signal-detection pipeline if not, classifies the resulting articles into 12 investment-research categories using an LLM, generates per-category summaries, and sends an HTML digest email via AWS SES.

It exposes two execution modes:
- **serve**: long-running FastAPI process with A2A endpoints (`/.well-known/agent.json`, `POST /` JSON-RPC) and webhook receivers
- **run**: one-shot CLI command invoked by an EventBridge cron rule (7 AM UTC daily)

## Jira Board
| Board | URL | Project Key |
|-------|-----|-------------|
| OCN Board | https://opengrowthventures.atlassian.net/jira/software/projects/CON/boards/34 | CON |

## Structure

See [STRUCTURE.md](STRUCTURE.md) for descriptions.

```
lucky-clarke/
├── Dockerfile
├── requirements.txt
├── requirements-test.txt
├── pyproject.toml
├── CLAUDE.md
├── STRUCTURE.md
├── README.md
└── src/
    ├── __main__.py             # Click group: serve, run
    ├── app.py                  # FastAPI factory
    ├── config.py               # CATEGORIES, EMAIL_RECIPIENTS, env vars
    ├── routes/
    │   ├── health.py           # GET /health
    │   ├── a2a.py              # GET /.well-known/agent.json; POST / (JSON-RPC)
    │   └── webhooks.py         # POST /webhook/news-retrieval, /webhook/signal-detection
    ├── controllers/
    │   └── digest.py           # Pipeline orchestration
    └── adapters/
        ├── signal_client.py    # signal-detection HTTP client (POST /run, GET /classifications/*)
        ├── llm_client.py       # OpenRouter: categorisation + summaries
        └── smtp_sender.py      # SMTP sender (smtplib, STARTTLS)
```

## Guidance

- Use the Jira board (project key `CON`) to track and reference cards
- The `run` command uses polling; the A2A `tasks/send` path dispatches asynchronously via `BackgroundTasks` (also polling under the hood)
- `EMAIL_RECIPIENTS` is hardcoded in `src/config.py`
- SES sender identity must be verified in AWS before deployment
- The `composite_score` field from signal-detection is currently a placeholder (0.0) pending CON-138; category summaries will improve once real scores are populated

## Maintenance

- Do not modify the Jira Board or Maintenance sections unless explicitly asked
- When adding email recipients, update `EMAIL_RECIPIENTS` in `src/config.py`
- When adding or modifying categories, update `CATEGORIES` in `src/config.py`
