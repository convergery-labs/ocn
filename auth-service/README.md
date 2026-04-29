# auth-service

Part of the [ocn monorepo](../README.md). See root README for full system setup.

TODO: Add a one-line description of what this service does.

## Stack

TODO: List runtime stack (framework, database, etc.)

## Quick Start

```bash
# From the repo root (build context must be the repo root)
docker compose up postgres-auth auth-service
```

TODO: Add service-specific setup steps.

## Environment Variables

TODO: Document required and optional environment variables.

## API

TODO: List endpoints with auth requirements and descriptions.

## Testing

```bash
# From the repo root
docker compose up postgres-auth -d
pip install -r auth-service/requirements-test.txt
pytest auth-service/tests/
```
