# Structure

## Root

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build (`base`, `dev`); build context is repo root (`docker build .`); copies `auth-service/src/` and `shared/src/` into `/app`; sets `PYTHONPATH=/app/shared`; runs on port 8001 |
| `requirements.txt` | Production dependencies (fastapi, uvicorn, psycopg2-binary, pydantic, click) |
| `requirements-test.txt` | Test-only dependencies (pytest, pytest-asyncio, httpx) |
| `pyproject.toml` | Pytest config (`asyncio_mode=auto`, `testpaths=["tests"]`) |

## App Layers

| Layer | File | Responsibility |
|-------|------|---------------|
| Entry point | `src/__main__.py` | `init_db` → `seed_admin_key` → `seed_admin_user` → `uvicorn.run`; never imports routes |
| App factory | `src/app.py` | Assembles `FastAPI`, registers routers; no DB or seed logic |
| Routes | `src/routes/health.py` | `GET /health` — liveness check |
| Routes | `src/routes/auth.py` | `POST /register`, `POST /login` — public endpoints; no auth required |
| Routes | `src/routes/keys.py` | `GET /keys`, `POST /keys` — HTTP only, delegates to models |
| Routes | `src/routes/validate.py` | `POST /validate` — HTTP only, delegates to models |
| Routes | `src/routes/jwks.py` | `GET /jwks` — unauthenticated; returns RS256 public key in JWKS format |
| Auth | `src/auth.py` | `require_auth`, `require_admin` FastAPI dependencies |
| Models | `src/models/api_keys.py` | `ApiKeyRow`, `generate_key`, `hash_key`, CRUD functions |
| Models | `src/models/users.py` | `UserRow`, `create_user`, `get_user_by_username`, `update_last_login` |
| Models | `src/models/domains.py` | `DomainRow`, `get_domains_by_slugs`, `get_domain_slugs_for_user`, `attach_domains_to_user` |
| JWT | `src/jwt_utils.py` | `issue_token()` — RS256 JWT issuance via `AUTH_JWT_PRIVATE_KEY` env var (PEM) |
| Infrastructure | `src/db.py` | Thin adapter: `_new_connection` (reads `AUTH_POSTGRES_*`), `init_db`, `db_utils.configure()`; re-exports `get_db` and `DuplicateError` from `shared/src/db_utils.py` |
| Seed | `src/seed.py` | `seed_admin_key()`, `seed_admin_user()` — idempotent, called from entry point only |

## HTTP API

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | none | Liveness check; returns `{"status": "ok"}` |
| `POST` | `/register` | none | Create user account; returns `{id, username, email, role, domains}` (201); 409 on duplicate; 404 on unknown domain slug |
| `POST` | `/login` | none | Verify credentials; returns `{access_token, token_type}` with RS256 JWT; 401 on bad credentials; 403 if inactive |
| `GET` | `/jwks` | none | RS256 public key as JWKS; no auth required |
| `GET` | `/keys` | admin | List all keys (hashes excluded) |
| `POST` | `/keys` | admin | Create key; returns plaintext once (201) |
| `POST` | `/validate` | Bearer token in header | Validate a key; returns `{valid, role, key_id}` |

## Testing

Run from the repo root:

```bash
# Start the test sidecar (port 5434)
docker compose up -d postgres-auth-test

# Install test dependencies
pip install -r auth-service/requirements-test.txt

# Run suite
AUTH_POSTGRES_PORT=5434 pytest auth-service/tests/
```

The test suite creates and wipes `auth-service-test` automatically.

| File | Covers |
|------|--------|
| `tests/conftest.py` | DB setup, RSA key pair generation, `admin_key`, `user_key`, `seed_domains`, async `client` fixtures |
| `tests/test_auth.py` | `POST /register`, `POST /login` — happy paths, duplicate/unknown domain, wrong password, inactive account |
| `tests/test_keys.py` | `GET /keys`, `POST /keys` — auth enforcement, response shape |
| `tests/test_validate.py` | `POST /validate` — valid keys, unknown keys, missing/malformed headers |
| `tests/test_jwks.py` | `GET /jwks` — response shape, public key verifies issued JWT |
