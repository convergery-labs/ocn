# OCN News Aggregator

Fetches RSS feeds, categorises articles by domain and taxonomy using LLMs, and generates themed markdown reports.

## Stack

- **Server**: FastAPI + uvicorn
- **Database**: PostgreSQL (persisted via Docker volume)
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
| `POSTGRES_HOST` | No | PostgreSQL host (default: `localhost`) |
| `POSTGRES_PORT` | No | PostgreSQL port (default: `5432`) |
| `POSTGRES_DB` | No | Database name (default: `news-retrieval`) |
| `POSTGRES_USER` | No | Database user (default: `news-retrieval`) |
| `POSTGRES_PASSWORD` | Yes | Database password |

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/run` | Fetch, categorise, and generate reports for a domain |
| `GET` | `/runs` | List all pipeline runs, newest first |
| `GET` | `/runs/{run_id}` | Get a single pipeline run by ID |
| `GET` | `/runs/{run_id}/reports` | List all reports for a run |
| `GET` | `/runs/{run_id}/reports/download` | Download all reports for a run as a ZIP |
| `GET` | `/reports/{report_id}` | Get a report record with its markdown content |
| `GET` | `/reports/{report_id}/download` | Download a report as a markdown file |
| `GET` | `/domains` | List all domains |
| `POST` | `/domains` | Create a domain with inline taxonomy |
| `GET` | `/sources` | List all sources (optional `?domain=` filter) |
| `POST` | `/sources` | Add a new RSS feed source |
| `GET` | `/frequencies` | List all polling frequencies |
| `POST` | `/frequencies` | Add a new polling frequency |
| `GET` | `/taxonomies` | List all taxonomy categories (optional `?domain=` filter) |
| `POST` | `/taxonomies` | Add a category to a domain's taxonomy |
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
