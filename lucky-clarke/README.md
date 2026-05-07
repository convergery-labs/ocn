# lucky-clarke

A2A-compatible daily AI news digest agent. Runs every 24 hours, classifies articles into 12 investment-research categories, generates LLM summaries, and sends an HTML email digest via AWS SES.

## Quick Start

```bash
# Copy and populate env vars
cp lucky-clarke/.env.example lucky-clarke/.env

# Run the A2A server
docker compose up lucky-clarke

# Smoke test
curl http://localhost:8005/health
curl http://localhost:8005/.well-known/agent.json

# One-shot digest run (cron mode)
docker compose run --rm lucky-clarke python -m src run
```

## Modes

| Command | Description |
|---------|-------------|
| `python -m src serve` | Start the FastAPI A2A server on port 8005 |
| `python -m src run` | Run the one-shot digest pipeline and exit |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `NEWS_RETRIEVAL_URL` | Yes | URL of news-retrieval service |
| `SIGNAL_DETECTION_URL` | Yes | URL of signal-detection service |
| `LUCKY_CLARKE_URL` | Yes | Self-reference URL (for webhook callbacks) |
| `NEWS_RETRIEVAL_API_KEY` | Yes | Bearer token for news-retrieval |
| `SIGNAL_DETECTION_API_KEY` | Yes | Bearer token for signal-detection |
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key |
| `OPENROUTER_MODEL` | No | Model string (default: `openai/gpt-4o-mini`) |
| `SMTP_HOST` | Yes | SMTP server hostname |
| `SMTP_PORT` | No | SMTP port (default: `587`) |
| `SMTP_USER` | Yes | SMTP login username |
| `SMTP_PASSWORD` | Yes | SMTP login password |
| `SMTP_FROM` | Yes | Sender address |

## A2A Interface

Send a digest task:
```bash
curl -X POST http://localhost:8005/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tasks/send","params":{}}'
```

## Tests

```bash
pip install -r lucky-clarke/requirements-test.txt
pytest lucky-clarke/tests/
```
