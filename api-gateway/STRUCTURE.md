# Structure

## Root

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build (`base`, `dev`); build context is repo root (`docker build .`); copies `api-gateway/requirements.txt` and `api-gateway/src/` into `/app`; runs uvicorn on port 8004 |
| `requirements.txt` | Production dependencies (fastapi, uvicorn, httpx, click) |
| `requirements-test.txt` | Test-only dependencies (pytest, pytest-asyncio, httpx) |
| `pyproject.toml` | Pytest config (`asyncio_mode=auto`, `testpaths=["tests"]`) |
| `.env.example` | Documents all required `GATEWAY_*` env vars |

## App Layers

| Layer | File | Responsibility |
|-------|------|---------------|
| Entry point | `src/__main__.py` | Click CLI → `uvicorn.run`; no DB or seed logic |
| App factory | `src/app.py` | Assembles `FastAPI`, registers routers; no I/O |
| Routes | `src/routes/health.py` | `GET /health` — validates upstream URL config |
| Routes | `src/routes/proxy_routes.py` | Catch-all proxy routes per upstream service |
| Auth | `src/auth.py` | `require_auth` / `require_admin` FastAPI dependencies |
| Infrastructure | `src/proxy.py` | `forward_request()` using a shared `httpx.AsyncClient` |

Dependencies flow one way: `__main__` → `app` → `routes` → `auth` / `proxy`.

## Proxy Forwarding Flow

```
Client request
    │
    ▼
/auth/{path}  ──►  proxy_auth()   ──►  forward_request(GATEWAY_AUTH_URL, path)
/news/{path}  ──►  proxy_news()   ──►  forward_request(GATEWAY_NEWS_URL, path)
/signal/{path}──►  proxy_signal() ──►  forward_request(GATEWAY_SIGNAL_URL, path)
    │
    ▼
httpx.AsyncClient
    │
    ▼
Upstream service response (status + headers + body)
    │
    ▼
Client response
```

Hop-by-hop headers (`connection`, `transfer-encoding`, `host`, etc.) are
stripped in both directions. Query parameters are forwarded unchanged.
A `502` is returned if the upstream is unreachable (`httpx.RequestError`).

## HTTP API

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | none | 200 if all `GATEWAY_*` URLs are set; 503 otherwise |
| `GET` | `/auth/jwks` | none | Proxied to auth-service `/jwks`; public |
| `*` | `/auth/{path}` | `require_auth` | Proxied to `GATEWAY_AUTH_URL/{path}` |
| `POST` | `/news/run` | `require_auth` + domain scope | Proxied to `GATEWAY_NEWS_URL/run`; JWT callers checked against token `domains` |
| `*` | `/news/{path}` | `require_auth` | Proxied to `GATEWAY_NEWS_URL/{path}` |
| `*` | `/signal/{path}` | `require_admin` | Proxied to `GATEWAY_SIGNAL_URL/{path}` (admin only) |

Auth is enforced at the gateway via Bearer token inspection. JWTs (three
dot-separated segments) are verified locally against the RS256 public key
fetched from `GET {GATEWAY_AUTH_URL}/jwks` and cached for the process
lifetime. API keys are validated via `POST {GATEWAY_AUTH_URL}/validate`.
In both cases the caller identity is propagated downstream via an
`x-ocn-caller` header (base64-encoded JSON containing `sub`, `role`, and
`domains`). JWT callers hitting `POST /news/run` have their domain claim
checked at the gateway before proxying; admin callers bypass this check.

## Testing

Run from the repo root:

```bash
# Install test dependencies
pip install -r api-gateway/requirements-test.txt

# Run suite
cd api-gateway && pytest tests/ -v
```

Or via Docker:

```bash
docker compose run --rm --build api-gateway pytest tests/ -v
```

| File | Covers |
|------|--------|
| `tests/conftest.py` | ASGI `client` fixture with all `GATEWAY_*` vars pre-set |
| `tests/test_health.py` | `/health` — 200 when all vars set, 503 when one is missing |
| `tests/test_auth.py` | missing token → 401; unknown → 401; wrong role → 403; valid admin → 200; `x-ocn-caller` header propagated downstream |
| `tests/test_jwt_auth.py` | valid JWT → 200; expired → 401; tampered → 401; domain mismatch → 403; admin bypass; `x-ocn-caller` from JWT claims |
