# ocn

Monorepo for the OCN platform: auth, news retrieval, and signal detection.

## Services

| Service | Port | Description |
|---------|------|-------------|
| [auth-service](auth-service/README.md) | 8001 | Authentication and API key management |
| [news-retrieval](news-retrieval/README.md) | 8000 | RSS feed fetching and LLM-based relevance filtering |
| [signal-detection](signal-detection/README.md) | 8002 | Signal detection and vector-similarity pipelines |

## Stack

- **Services**: FastAPI + uvicorn (Python 3.12)
- **Databases**: PostgreSQL (one sidecar per service)
- **Vector store**: Qdrant (signal-detection)
- **LLM**: Configurable via OpenRouter (news-retrieval)
- **Infrastructure**: Docker Compose
- **Shared utilities**: `shared/src/` — PostgreSQL connection helpers and keyset-pagination cursor utilities, copied into each service image at build time

## Quick start

```bash
cp auth-service/.env.example auth-service/.env
cp news-retrieval/.env.example news-retrieval/.env
cp signal-detection/.env.example signal-detection/.env
cp api-gateway/.env.example api-gateway/.env
# Fill in required values in each .env file

docker compose up
```

> **Note:** All service Docker images are built with the repo root as the build context so that `shared/src/` can be copied in. Always run `docker compose` (or `docker build`) from the repo root.

All three services start automatically with their PostgreSQL sidecars.
Qdrant starts alongside `signal-detection`.

Health checks:

```bash
curl http://localhost:8001/health   # auth-service
curl http://localhost:8000/health   # news-retrieval
curl http://localhost:8002/health   # signal-detection
```

## Deploying to ECS

Images must be built for `linux/amd64` regardless of the host OS. Use the Makefile targets — they bake in the correct platform flag and the ECR registry URL.

```bash
# Authenticate to ECR (once per session)
make ecr-login

# Build and push a single service
make push-auth
make push-news
make push-signal

# Build and push all three (includes ecr-login)
make push-all
```

Individual `push-*` targets do not authenticate — run `make ecr-login` first if your session has expired.

See [infra/README.md](infra/README.md) for Terraform apply instructions.

## Connecting to RDS locally

RDS is in a private subnet. Use the Makefile target to tunnel through the bastion via SSM (requires the [SSM Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)):

```bash
make tunnel-rds
```

Then connect DBeaver (or any Postgres client) to `localhost:5433`.

## Environment variables

Each service has its own `.env.example` listing only the variables it needs:

| Service | File |
|---------|------|
| auth-service | [auth-service/.env.example](auth-service/.env.example) |
| news-retrieval | [news-retrieval/.env.example](news-retrieval/.env.example) |
| signal-detection | [signal-detection/.env.example](signal-detection/.env.example) |
| api-gateway | [api-gateway/.env.example](api-gateway/.env.example) |

## Testing

Run all test suites:

```bash
docker compose up postgres-auth postgres-news postgres-signal -d

pip install -r auth-service/requirements-test.txt
pip install -r news-retrieval/requirements-test.txt
pip install -r signal-detection/requirements-test.txt

pytest auth-service/tests/
pytest news-retrieval/tests/
pytest signal-detection/tests/
```

Or run a single service in isolation:

```bash
pytest news-retrieval/tests/
```

Each service's test suite manages its own database setup and teardown via `conftest.py`.
