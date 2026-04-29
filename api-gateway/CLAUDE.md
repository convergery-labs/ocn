# api-gateway

Part of the [ocn monorepo](../CLAUDE.md).

## Overview

`api-gateway` is a db-less reverse proxy that sits in front of the OCN
microservices. It forwards requests to the appropriate upstream (auth-service,
news-retrieval, signal-detection) based on the URL prefix, reading all
upstream base URLs from environment variables. No business logic lives here.

## Jira Board
| Board | URL | Project Key |
|-------|-----|-------------|
| OCN Board | https://opengrowthventures.atlassian.net/jira/software/projects/CON/boards/34 | CON |

## Structure

See [STRUCTURE.md](STRUCTURE.md) for descriptions.

```
api-gateway/
├── Dockerfile            # build context: repo root (.); COPY paths prefixed api-gateway/
├── requirements.txt
├── requirements-test.txt
├── pyproject.toml
├── .env.example
├── CLAUDE.md
├── STRUCTURE.md
├── README.md
├── src/
│   ├── __main__.py         # Entry point: uvicorn.run (no DB init)
│   ├── app.py              # FastAPI app factory
│   ├── auth.py             # require_auth / require_admin FastAPI deps
│   ├── proxy.py            # Generic async HTTP proxy (httpx.AsyncClient)
│   └── routes/
│       ├── health.py       # GET /health
│       └── proxy_routes.py # /auth/*, /news/*, /signal/* catch-alls
└── tests/
    ├── conftest.py          # ASGI client fixture
    ├── test_health.py       # /health endpoint tests
    └── test_auth.py         # auth enforcement + public route tests
```

## Documentation

| Title | Confluence URL |
|-------|---------------|
| Technical Specification — API Gateway | https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/86900737/Technical+Specification+API+Gateway |

## Guidance

- Read only the docs relevant to your task
- Use the Jira board (project key `CON`) to track and reference cards
- All upstream URLs are configured via `GATEWAY_*` env vars — never hardcode

## Maintenance

- Do not modify the Jira Board, Guidance, or Maintenance sections unless
  explicitly asked
