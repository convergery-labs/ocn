# OCN News Aggregator

Fetches RSS feeds, categorises articles by domain and taxonomy using LLMs, and generates themed markdown reports.

## Stack

- **Server**: FastAPI + uvicorn
- **Database**: SQLite (persisted via Docker volume)
- **LLMs**: `openai/gpt-4o-mini` (categorisation) and `anthropic/claude-haiku-4-5` (report generation) via OpenRouter

## Quick start

```bash
# Copy .env.example and add your key
cp .env.example .env

docker compose up
```

The API is available at `http://localhost:8000`. Interactive docs at `/docs`.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENROUTER_API_KEY` | Yes | API key for OpenRouter |
| `REPORTS_DIR` | No | Output directory for reports (default: `/app/reports`) |
| `DB_PATH` | No | SQLite database path (default: `/app/data/sources.db`) |

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/run` | Fetch, categorise, and generate reports |
| `GET` | `/domains` | List all domains |
| `POST` | `/domains` | Create a domain with inline taxonomy |
| `GET` | `/sources` | List all sources |
| `POST` | `/sources` | Add a source |
| `GET` | `/frequencies` | List frequencies |
| `GET` | `/taxonomies` | List taxonomy categories |
| `GET` | `/health` | Health check |

### Run the pipeline

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"domain": "ai_news", "days_back": 7}'
```

Reports are written to `./reports/` as markdown files, one per qualifying category.

### Add a domain with taxonomy

```bash
curl -X POST http://localhost:8000/domains \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Domain",
    "slug": "my_domain",
    "taxonomy": [
      {"category": "Category A"},
      {"category": "Category B"}
    ]
  }'
```
