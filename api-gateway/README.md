# api-gateway

Part of the [ocn monorepo](../README.md). See root README for full system
setup.

A db-less reverse proxy that routes requests to the correct OCN upstream
service based on the URL prefix.

## Stack

- **Framework**: FastAPI
- **Server**: uvicorn
- **HTTP client**: httpx (async)

## Quick Start

```bash
# From the repo root
docker compose up api-gateway
```

The gateway listens on port **8003**.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GATEWAY_AUTH_URL` | yes | — | Base URL of auth-service |
| `GATEWAY_NEWS_URL` | yes | — | Base URL of news-retrieval |
| `GATEWAY_SIGNAL_URL` | yes | — | Base URL of signal-detection |

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | 200 if all upstream URLs configured; 503 otherwise |
| `*` | `/auth/{path}` | Proxy to auth-service |
| `*` | `/news/{path}` | Proxy to news-retrieval |
| `*` | `/signal/{path}` | Proxy to signal-detection |

### Example: health check

```bash
curl http://localhost:8003/health
# {"status": "ok"}
```

### Example: proxied request

```bash
# Reaches auth-service GET /health via the gateway
curl http://localhost:8003/auth/health
# {"status": "ok"}
```

Auth headers are passed through unchanged to the upstream service.

## Testing

```bash
# From the repo root
pip install -r api-gateway/requirements-test.txt
cd api-gateway && pytest tests/ -v
```
