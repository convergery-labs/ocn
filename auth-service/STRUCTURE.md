# Structure

## Root

| File | Purpose |
|------|---------|
| `Dockerfile` | Build image: copies `src/` flat into `/app`, runs on port 8001 |
| `requirements.txt` | Production dependencies (fastapi, uvicorn, psycopg2-binary, pydantic, click) |
| `requirements-test.txt` | Test-only dependencies (pytest, pytest-asyncio, httpx) |
| `pyproject.toml` | Pytest config (`asyncio_mode=auto`, `testpaths=["tests"]`) |

## App Layers

| Layer | File | Responsibility |
|-------|------|---------------|
| Entry point | `src/__main__.py` | `init_db` → `seed_admin_key` → `uvicorn.run`; never imports routes |
| App factory | `src/app.py` | Assembles `FastAPI`, registers routers; no DB or seed logic |
| Routes | `src/routes/health.py` | `GET /health` — liveness check |
| Routes | `src/routes/keys.py` | `GET /keys`, `POST /keys` — HTTP only, delegates to models |
| Routes | `src/routes/validate.py` | `POST /validate` — HTTP only, delegates to models |
| Auth | `src/auth.py` | `require_auth`, `require_admin` FastAPI dependencies |
| Models | `src/models/api_keys.py` | `ApiKeyRow`, `generate_key`, `hash_key`, CRUD functions |
| Infrastructure | `src/db.py` | psycopg2 connection (`AUTH_POSTGRES_*`), `_Connection` wrapper, `init_db` |
| Seed | `src/seed.py` | `seed_admin_key()` — idempotent, called from entry point only |

## HTTP API

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | none | Liveness check; returns `{"status": "ok"}` |
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
| `tests/conftest.py` | DB setup, `admin_key`, `user_key`, async `client` fixtures |
| `tests/test_keys.py` | `GET /keys`, `POST /keys` — auth enforcement, response shape |
| `tests/test_validate.py` | `POST /validate` — valid keys, unknown keys, missing/malformed headers |
