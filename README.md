# ocn

Monorepo for the OCN platform: auth, news retrieval, and signal detection.

## Services

| Service | Port | Description |
|---------|------|-------------|
| [auth-service](auth-service/README.md) | 8001 | Authentication and API key management |
| [news-retrieval](news-retrieval/README.md) | 8000 | RSS feed fetching and LLM-based relevance filtering |
| [signal-detection](signal-detection/README.md) | 8002 | Signal detection and vector-similarity pipelines |

## Stack

- **Services**: FastAPI + uvicorn (Python 3.12)
- **Databases**: PostgreSQL (one sidecar per service)
- **Vector store**: Qdrant (signal-detection)
- **LLM**: Configurable via OpenRouter (news-retrieval)
- **Infrastructure**: Docker Compose

## Quick start

```bash
cp .env.example .env
# Fill in required values in .env

docker compose up
```

All three services start automatically with their PostgreSQL sidecars.
Qdrant starts alongside `signal-detection`.

Health checks:

```bash
curl http://localhost:8001/health   # auth-service
curl http://localhost:8000/health   # news-retrieval
curl http://localhost:8002/health   # signal-detection
```

## Environment variables

See [.env.example](.env.example) for the full list, grouped by service.

## Testing

Run all test suites:

```bash
docker compose up postgres-auth postgres-news postgres-signal -d

pip install -r auth-service/requirements-test.txt
pip install -r news-retrieval/requirements-test.txt
pip install -r signal-detection/requirements-test.txt

pytest auth-service/tests/
pytest news-retrieval/tests/
pytest signal-detection/tests/
```

Or run a single service in isolation:

```bash
pytest news-retrieval/tests/
```

Each service's test suite manages its own database setup and teardown via `conftest.py`.
