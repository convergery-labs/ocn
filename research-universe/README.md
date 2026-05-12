# research-universe

Discovers, classifies, and maintains the AlphaStreet AI Research Universe.

## Quick start

### 1. Bootstrap the Google Sheet (one-time)

```bash
GOOGLE_SERVICE_ACCOUNT=/path/to/service-account.json \
python -m src init-sheet --file /path/to/AlphaStreet_AI_Stocks_Research_Universe_v2.xlsx
# Prints: GOOGLE_SHEET_ID=<id>
```

Set the printed ID as `GOOGLE_SHEET_ID` in `research-universe/.env`.

### 2. Run

```bash
docker compose up research-universe

# Health check
curl http://localhost:8006/health

# Run pipeline (Phase 6+)
docker compose exec research-universe python -m src run
```

## Environment variables

| Variable | Description |
|----------|-------------|
| `GOOGLE_SHEET_ID` | Set after running `init-sheet` |
| `GOOGLE_SERVICE_ACCOUNT` | Path to service account JSON (local) or JSON string (ECS) |
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `OPENROUTER_MODEL` | e.g. `openai/gpt-4o-mini` |
| `TAVILY_API_KEY` | Tavily search API key |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage API key |
| `SIGNAL_DETECTION_URL` | signal-detection service URL (V2) |
| `SIGNAL_CALLER_SUB` | Caller sub header (V2, default: `1`) |
| `CRUNCHBASE_API_KEY` | Crunchbase API key (V2, optional) |
