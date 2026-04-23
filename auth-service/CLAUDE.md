# auth-service

Part of the [ocn monorepo](../CLAUDE.md).

## Overview

`auth-service` is a shared service for authenticating API requests as they come in. Both - `news-retrieval` as well as `signal-detection` safeguard their APIs with an authentication layer that depends on this service.

## Jira Board
| Board | URL | Project Key |
|-------|-----|-------------|
| OCN Board | https://opengrowthventures.atlassian.net/jira/software/projects/CON/boards/34 | CON |

## Structure

See [STRUCTURE.md](STRUCTURE.md) for descriptions.

```
auth-service/
├── Dockerfile
├── requirements.txt
├── requirements-test.txt
├── pyproject.toml
├── CLAUDE.md
├── STRUCTURE.md
├── README.md
├── src/
│   ├── __main__.py       # Entry point: init_db → seed_admin_key → uvicorn
│   ├── app.py            # FastAPI app factory
│   ├── auth.py           # require_auth / require_admin dependencies
│   ├── db.py             # psycopg2 connection, DuplicateError, init_db
│   ├── seed.py           # seed_admin_key() from AUTH_ADMIN_API_KEY
│   ├── models/
│   │   └── api_keys.py   # ApiKeyRow, generate_key, hash_key, CRUD
│   └── routes/
│       ├── health.py     # GET /health
│       ├── keys.py       # GET /keys, POST /keys
│       └── validate.py   # POST /validate
└── tests/
    ├── conftest.py        # DB setup, admin_key, user_key, client fixtures
    ├── test_keys.py       # /keys endpoint tests
    └── test_validate.py   # /validate endpoint tests
```

## Guidance

- Read only the docs relevant to your task
- Use the Jira board (project key `CON`) to track and reference cards

## Maintenance

- Do not modify the Jira Board, Guidance, or Maintenance sections unless explicitly asked
