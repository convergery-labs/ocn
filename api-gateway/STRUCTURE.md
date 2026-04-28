# Structure

## Root

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build: `base` runs uvicorn on port 8003; `test` adds pytest |
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
| Infrastructure | `src/proxy.py` | `forward_request()` using a shared `httpx.AsyncClient` |

Dependencies flow one way: `__main__` → `app` → `routes` → `proxy`.

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
| `*` | `/auth/{path}` | upstream | Proxied to `GATEWAY_AUTH_URL/{path}` |
| `*` | `/news/{path}` | upstream | Proxied to `GATEWAY_NEWS_URL/{path}` |
| `*` | `/signal/{path}` | upstream | Proxied to `GATEWAY_SIGNAL_URL/{path}` |

Auth is enforced by the upstream service, not the gateway.

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
