# signal-herald

## Overview
A2A-compatible daily digest service. Polls the signal-detection-agent for classified articles, groups them into 11 AI-universe categories, generates LLM-powered investment summaries via OpenRouter, and sends formatted HTML email digests.

Runs on **port 8006**. Scheduled daily at **14:00 UTC** via CloudWatch Events in staging.

## Architecture

```
routes/a2a.py          JSON-RPC dispatcher + agent card
routes/health.py       Liveness check
routes/webhooks.py     Webhook receiver stub (future use)
    ↓
controllers/digest.py  Pipeline orchestration
    ↓
adapters/
  signal_agent_client.py   HTTP client → signal-detection-agent
  llm_client.py            OpenRouter summaries (OpenAI-compatible SDK)
  smtp_sender.py           Gmail SMTP HTML email dispatch
```

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `GET` | `/.well-known/agent.json` | A2A agent card |
| `POST` | `/` | JSON-RPC 2.0 dispatcher (`tasks/send` → `run_digest`) |
| `POST` | `/webhooks/signal-agent` | Signal-agent webhook receiver (stub) |

## Running

```bash
# Server
python -m src serve --host 0.0.0.0 --port 8006

# One-shot digest (skips duplicate-run check)
python -m src run --force

# One-shot with existing job
python -m src run --job-id <uuid>
```

## Environment Variables

| Variable | Default | Secret | Description |
|----------|---------|--------|-------------|
| `SIGNAL_AGENT_URL` | `http://localhost:8003` | No | signal-detection-agent base URL |
| `SIGNAL_HERALD_URL` | `http://localhost:8006` | No | Self-reference URL (A2A callbacks) |
| `SIGNAL_CALLER_SUB` | `1` | No | Caller ID for x-ocn-caller auth header |
| `OPENROUTER_API_KEY` | — | **Yes** | OpenRouter API key |
| `OPENROUTER_MODEL` | `openai/gpt-4o-mini` | No | Model for category summaries |
| `SMTP_HOST` | — | **Yes** | SMTP server hostname |
| `SMTP_PORT` | `587` | No | SMTP port |
| `SMTP_USER` | — | **Yes** | SMTP login username |
| `SMTP_PASSWORD` | — | **Yes** | SMTP app password |
| `SMTP_FROM` | — | **Yes** | From address |
| `DIGEST_TEST_EMAIL` | — | No | Override all recipients (dev/test) |

Secrets (`OPENROUTER_API_KEY`, `SMTP_*`) are pulled from AWS Secrets Manager in staging/production.

## Categories
11 AI-universe investment categories (defined in `src/config.py`):
Minerals, Energy, Semiconductors, Hardware, Thermal, Data Centers, Cloud, Software, AI Data, AI Models, Applications

## Digest Pipeline
1. Check if a job already ran today (skip unless `--force`)
2. Trigger `POST /run` on signal-detection-agent (or reuse an existing job)
3. Poll job status every 30s, timeout after 1 hour
4. Fetch all classified results (paginated)
5. Group articles by category
6. Generate 3-4 sentence investment summary per category via OpenRouter
7. Render HTML email and dispatch via SMTP

## Infra
- ECS task: `{env}-signal-herald`, CPU 512 / Mem 1024
- CloudWatch rule: daily at 14:00 UTC, runs `python -m src run --force`
- ECR repo: `ocn/signal-herald`
- Security group: ingress port 8006 from VPC CIDR `10.0.0.0/16`
- Log group: `/ecs/{env}/signal-herald` (30-day retention)
