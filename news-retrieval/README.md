# news-retrieval

Fetches RSS feeds and categorises articles by domain and taxonomy using LLMs. Returns structured JSON with articles grouped by category.

## Stack

- **Server**: FastAPI + uvicorn
- **Database**: PostgreSQL (persisted via Docker volume)
- **LLM**: `openrouter/elephant-alpha` (categorisation) via OpenRouter

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
| `POSTGRES_HOST` | No | PostgreSQL host (default: `localhost`) |
| `POSTGRES_PORT` | No | PostgreSQL port (default: `5432`) |
| `POSTGRES_DB` | No | Database name (default: `news-retrieval`) |
| `POSTGRES_USER` | No | Database user (default: `news-retrieval`) |
| `POSTGRES_PASSWORD` | Yes | Database password |

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/run` | Fetch and categorise articles for a domain |
| `GET` | `/runs` | List all pipeline runs, newest first |
| `GET` | `/runs/{run_id}` | Get a single pipeline run by ID |
| `GET` | `/runs/{run_id}/categories` | List categories produced by a run |
| `GET` | `/runs/{run_id}/articles` | List all articles for a run (optional `?category_id=` filter) |
| `GET` | `/articles/{article_id}` | Get a single article by ID |
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

Response includes `categories` — a dict mapping each category name to its list of articles.

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
