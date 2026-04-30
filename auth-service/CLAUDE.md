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
├── Dockerfile            # build context: repo root (.); COPY paths prefixed auth-service/ and shared/
├── requirements.txt
├── requirements-test.txt
├── pyproject.toml
├── CLAUDE.md
├── STRUCTURE.md
├── README.md
├── src/
│   ├── __main__.py       # Entry point: init_db → seed_admin_key → seed_admin_user → uvicorn
│   ├── app.py            # FastAPI app factory
│   ├── auth.py           # require_auth / require_admin dependencies
│   ├── db.py             # thin adapter: _new_connection, init_db; re-exports get_db/DuplicateError from shared/src/db_utils.py
│   ├── jwt_utils.py      # issue_token() — RS256 JWT via AUTH_JWT_PRIVATE_KEY env var
│   ├── seed.py           # seed_admin_key(), seed_admin_user()
│   ├── models/
│   │   ├── api_keys.py   # ApiKeyRow, generate_key, hash_key, CRUD
│   │   ├── users.py      # UserRow, create_user, get_user_by_username, update_last_login
│   │   └── domains.py    # DomainRow, get_domains_by_slugs, get_domain_slugs_for_user, attach_domains_to_user
│   └── routes/
│       ├── health.py     # GET /health
│       ├── auth.py       # POST /register, POST /login (public)
│       ├── jwks.py       # GET /jwks (public — RS256 public key in JWKS format)
│       ├── keys.py       # GET /keys, POST /keys
│       ├── users.py      # GET /users, GET /users/{id}, PATCH /users/{id}
│       └── validate.py   # POST /validate
└── tests/
    ├── conftest.py        # DB setup, RSA key pair, admin_key, user_key, seed_domains, client fixtures
    ├── test_auth.py       # /register, /login endpoint tests
    ├── test_keys.py       # /keys endpoint tests
    ├── test_users.py      # /users endpoint tests
    └── test_validate.py   # /validate endpoint tests
```

## How to use this file
Do not load all documentation upfront. Read the index below,
identify which docs are relevant to your current task, and
fetch only those. Use the 'Read when' column as your guide.

## Documentation Index
| Doc | Read when | Page ID |
|-----|-----------|---------|
| [Technical Specification — auth-service](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/89620484/Technical+Specification+auth-service) | Making architectural or technical decisions about auth, schema, or JWT | 89620484 |

Confluence space: `Projects` — Cloud: `opengrowthventures.atlassian.net`

## Guidance

- Read only the docs relevant to your task
- Use the Jira board (project key `CON`) to track and reference cards

## Maintenance

- Do not modify the Jira Board, Guidance, or Maintenance sections unless explicitly asked
