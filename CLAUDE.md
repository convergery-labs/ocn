# ocn

## How to use this file
For service-specific context and documentation links, read the relevant service's CLAUDE.md.

Confluence space: `Projects` — Cloud: `opengrowthventures.atlassian.net`

## Services

| Service | Path | CLAUDE.md | Description |
|---------|------|-----------|-------------|
| `auth-service` | [auth-service/](auth-service/) | [auth-service/CLAUDE.md](auth-service/CLAUDE.md) | Authentication and API key management |
| `news-retrieval` | [news-retrieval/](news-retrieval/) | [news-retrieval/CLAUDE.md](news-retrieval/CLAUDE.md) | RSS feed fetching and LLM-based relevance filtering |
| `signal-detection` | [signal-detection/](signal-detection/) | [signal-detection/CLAUDE.md](signal-detection/CLAUDE.md) | Signal detection and vector-similarity pipelines |

## Jira Board
| Board | URL | Project Key |
|-------|-----|-------------|
| OCN Board | https://opengrowthventures.atlassian.net/jira/software/projects/CON/boards/34 | CON |

## Structure

See each service's STRUCTURE.md for detailed layer descriptions.

```
ocn/
├── CLAUDE.md
├── README.md
├── docker-compose.yml        # all services + sidecars
├── docker-compose.dev.yml    # dev overrides (hot reload, volume mounts)
├── .env.example              # all env vars, grouped by service
├── auth-service/             # see auth-service/STRUCTURE.md
│   ├── CLAUDE.md
│   ├── STRUCTURE.md
│   ├── README.md
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── src/
│   └── tests/
├── news-retrieval/           # see news-retrieval/STRUCTURE.md
│   ├── CLAUDE.md
│   ├── STRUCTURE.md
│   ├── README.md
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── src/
│   └── tests/
└── signal-detection/         # see signal-detection/STRUCTURE.md
    ├── CLAUDE.md
    ├── STRUCTURE.md
    ├── README.md
    ├── Dockerfile
    ├── requirements.txt
    ├── src/
    └── tests/
```

## Guidance
- For service-specific context (architecture, endpoints, DB schema, docs), read that service's CLAUDE.md
- When in doubt about scope or requirements, read that service's PRD first
- Use the Jira board (project key `CON`) to track and reference cards

## Maintenance
- When adding or removing a service, update the Services table and Structure tree above
- Do not modify the Documentation Index, Jira Board, Guidance, or Maintenance sections unless explicitly asked
- Each service's CLAUDE.md owns its own Structure section; update it there after restructuring
