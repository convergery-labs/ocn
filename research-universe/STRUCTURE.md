# research-universe - Structure

```
research-universe/
├── CLAUDE.md              Feature spec, DB schema, architecture, API reference
├── STRUCTURE.md           This file
├── Dockerfile             Multi-stage build (base / dev)
├── requirements.txt       Python dependencies
├── .env.example           All env vars with descriptions
└── src/
    ├── __main__.py        CLI entry point (serve, scan-next, users create/list/rotate)
    ├── app.py             FastAPI factory - CORS, API_PREFIX middleware, router wiring
    ├── auth.py            Bearer token validation - bcrypt API keys (ru_ prefix); Google OAuth planned v2
    ├── config.py          Env var config
    ├── db.py              DB connection, init_db() - creates all tables + startup cleanup
    ├── seed.py            One-time xlsx → DB seed script (run as ECS task on first deploy)
    ├── agent/
    │   ├── agent.py       Claude tool-use loop - conversation history, tool dispatch
    │   ├── enrichment.py  Universe enrichment logic - LLM call, dedup, DB writes
    │   ├── prompts.py     System prompt, FIND_PEERS_PROMPT, ENRICHMENT_PROMPT
    │   └── tools.py       9 tool definitions + executors wired to DB models
    ├── models/
    │   ├── company.py     universe_companies CRUD + fuzzy search
    │   ├── conversation.py universe_conversations load/save
    │   ├── scan_job.py    universe_scan_jobs create/get/update
    │   ├── taxonomy.py    universe_taxonomy CRUD + schedule helpers
    │   └── user.py        universe_users create/lookup/rotate (bcrypt)
    └── routes/
        ├── chat.py        POST /chat
        ├── companies.py   GET /companies/search, /pending, /{id}; POST /{id}/verify
        ├── health.py      GET /health (checks DB connectivity)
        ├── jobs.py        POST /jobs/scan, /jobs/scan/next; GET /jobs/scan/{id}, /jobs/schedule
        ├── taxonomy.py    GET /taxonomy/categories, /subcategories, /search; POST /taxonomy/*
        └── users.py       GET /users/me, /users; POST /users, /users/rotate; DELETE /users/{id}
```

## Key flows

| Flow | Entry point |
|------|-------------|
| Chat / company lookup | `POST /chat` → `agent/agent.py` → tools → DB |
| Add company | Agent calls `create_company` tool → `models/company.py` |
| Peer discovery | Agent calls `find_peers` tool → `agent/tools.py` → OpenRouter |
| Manual enrichment scan | `POST /jobs/scan` → `agent/enrichment.py` (background) |
| Scheduled scan (CloudWatch) | `python -m src scan-next` → `agent/enrichment.py` (foreground) |
| Pending review | `GET /companies/pending` → `POST /companies/{id}/verify` |
| User management | `python -m src users create/list/rotate` |

## Ports

| Environment | Port |
|-------------|------|
| Local (Docker) | 8007 |
| Production (ECS) | 8007 |
| ALB path prefix | `/universe` |
