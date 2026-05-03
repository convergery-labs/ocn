# auth-service

Part of the [ocn monorepo](../README.md). See root README for full system setup.

Shared authentication service for the OCN platform. Issues RS256 JWTs on
login, validates API keys, and manages users and API key credentials.

## Stack

- **Framework**: FastAPI
- **Server**: uvicorn (port 8001)
- **Database**: PostgreSQL (psycopg2)
- **Auth**: RS256 JWT (PyJWT + cryptography), bcrypt password hashing

## Quick Start

```bash
# From the repo root (build context must be the repo root)
docker compose up postgres-auth auth-service
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AUTH_POSTGRES_HOST` | no | `localhost` | PostgreSQL host |
| `AUTH_POSTGRES_PORT` | no | `5432` | PostgreSQL port |
| `AUTH_POSTGRES_DB` | no | `auth-service` | Database name |
| `AUTH_POSTGRES_USER` | no | `auth-service` | Database user |
| `AUTH_POSTGRES_PASSWORD` | no | _(empty)_ | Database password |
| `PGSSLMODE` | no | `prefer` | PostgreSQL SSL mode |
| `AUTH_JWT_PRIVATE_KEY` | **yes** | — | PEM-encoded RS256 private key for JWT signing |
| `AUTH_JWT_EXPIRY_SECONDS` | no | `3600` | JWT lifetime in seconds |
| `AUTH_ADMIN_API_KEY` | **yes** | — | Seed admin API key (must start with `csec_`) |
| `ADMIN_USERNAME` | **yes** | — | Seed admin user username |
| `ADMIN_EMAIL` | **yes** | — | Seed admin user email |
| `ADMIN_PASSWORD` | **yes** | — | Seed admin user password |

## API

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | none | Liveness check; returns `{"status": "ok"}` |
| `GET` | `/jwks` | none | RS256 public key in JWKS format |
| `POST` | `/register` | none | Create user; returns `{id, username, email, role, domains}` (201) |
| `POST` | `/login` | none | Verify credentials; returns `{access_token, token_type}` |
| `GET` | `/keys` | `X-OCN-Caller` (admin) | List all API keys (hashes excluded) |
| `POST` | `/keys` | `X-OCN-Caller` (admin) | Create API key; returns plaintext once (201) |
| `POST` | `/validate` | Bearer token | Validate an API key; returns `{valid, role, key_id}` |

## Testing

```bash
# From the repo root
docker compose up postgres-auth-test -d
pip install -r auth-service/requirements-test.txt
AUTH_POSTGRES_PORT=5434 pytest auth-service/tests/
```
