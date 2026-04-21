# ocn

## How to use this file
Do not load all documentation upfront. Read the index below,
identify which docs are relevant to your current task, and
fetch only those. Use the 'Read when' column as your guide.
For service-specific context, read the relevant service's CLAUDE.md.

## Documentation Index
| Doc | Read when | Page ID |
|-----|-----------|---------|
| [Technical Specifications](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/30113793/Technical+Specifications) | Making architectural or technical decisions | 30113793 |
| ↳ [AISquare Publishing Pipeline — Implementation Plan](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/38043649/AISquare+Publishing+Pipeline+—+Implementation+Plan) | Working on the publishing or delivery flow | 38043649 |
| ↳ [OCN News Aggregator — Optimization Plan](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/35651593/OCN+News+Aggregator+—+Optimization+Plan) | Improving performance or efficiency | 35651593 |
| &nbsp;&nbsp;↳ [Bottleneck 1: Low-Signal Feeds](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/35946498/Bottleneck+1%3A+Low-Signal+Feeds) | Working on feed quality or relevance filtering | 35946498 |
| &nbsp;&nbsp;↳ [Bottleneck 2: Pre-filtering Articles by Title](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/36143105/Bottleneck+2%3A+Pre-filtering+Articles+by+Title) | Working on pre-LLM article filtering | 36143105 |
| &nbsp;&nbsp;↳ [Bottleneck 3: LLM Context Explosion](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/35880962/Bottleneck+3%3A+LLM+Context+Explosion) | Working on LLM token usage or prompt efficiency | 35880962 |
| [Sources](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/28705610/Sources) | Adding, removing, or evaluating data sources | 28705610 |
| [PRD](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/28705568/PRD) | Implementing or questioning any feature | 28705568 |
| [Roadmap](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/28508185/Roadmap) | Planning, scoping, or prioritising work | 28508185 |

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
- Read only the docs relevant to your task — not all of them
- Check the index above before asking for clarification; the answer is often in a doc
- When in doubt about scope or requirements, read the PRD first
- For service-specific context (architecture, endpoints, DB schema), read that service's CLAUDE.md
- Use the Jira board (project key `CON`) to track and reference cards

## Maintenance
- When adding or removing a service, update the Services table and Structure tree above
- Do not modify the Documentation Index, Jira Board, Guidance, or Maintenance sections unless explicitly asked
- Each service's CLAUDE.md owns its own Structure section; update it there after restructuring
