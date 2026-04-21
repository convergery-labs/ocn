# signal-detection

Part of the [ocn monorepo](../README.md). See root README for full system setup.

TODO: Add a one-line description of what this service does.

## Stack

TODO: List runtime stack (framework, database, vector store, etc.)

- **Vector store**: Qdrant

## Quick Start

```bash
# From the repo root
docker compose up postgres-signal qdrant signal-detection
```

TODO: Add service-specific setup steps.

## Environment Variables

TODO: Document required and optional environment variables.

| Variable | Required | Description |
|----------|----------|-------------|
| `SIGNAL_POSTGRES_PASSWORD` | Yes | PostgreSQL password |
| `QDRANT_HOST` | No | Qdrant hostname (default: `qdrant`) |
| `QDRANT_PORT` | No | Qdrant port (default: `6333`) |

## Qdrant

TODO: Document collections, embedding models used, and query patterns.

## API

TODO: List endpoints with auth requirements and descriptions.

## Testing

```bash
# From the repo root
docker compose up postgres-signal qdrant -d
pip install -r signal-detection/requirements-test.txt
pytest signal-detection/tests/
```
