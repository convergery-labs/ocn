# ocn

## How to use this file
Do not load all documentation upfront. Read the index below,
identify which docs are relevant to your current task, and
fetch only those. Use the 'Read when' column as your guide.

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

## Jira Board
| Board | URL | Project Key |
|-------|-----|-------------|
| ocn Board | https://opengrowthventures.atlassian.net/jira/software/projects/CON/boards/34 | CON |

## Structure

See [STRUCTURE.md](STRUCTURE.md) for descriptions.

```
ocn/
├── Dockerfile
├── docker-compose.yml
├── AgentCard.json
├── README.md
├── CLAUDE.md
├── STRUCTURE.md
├── data/                 # SQLite database (Docker volume)
├── reports/              # generated — one .md per category per run
└── src/
    ├── __main__.py       # CLI entry point (uvicorn + click)
    ├── app.py            # FastAPI app factory and lifespan
    ├── pipeline.py       # Two-pass aggregation pipeline (fetch → categorise → report)
    ├── db.py             # SQLite connection, context manager, schema init
    ├── seed.py           # Idempotent seed for frequencies, domains, taxonomies, sources
    ├── models/           # DB query functions + Pydantic models (repository layer)
    │   ├── domains.py
    │   ├── frequencies.py
    │   ├── sources.py
    │   └── taxonomies.py
    ├── controllers/      # Business logic and multi-step orchestration
    │   ├── domains.py
    │   ├── frequencies.py
    │   ├── run.py
    │   ├── sources.py
    │   └── taxonomies.py
    └── routes/           # Thin HTTP adapters (FastAPI APIRouters)
        ├── domains.py
        ├── frequencies.py
        ├── health.py
        ├── run.py
        ├── sources.py
        └── taxonomies.py
```

## Guidance
- Read only the docs relevant to your task — not all of them
- Check the index above before asking for clarification; the answer is often in a doc
- When in doubt about scope or requirements, read the Functional Requirements or PRD first
- Use the Jira board (project key `CON`) to track and reference cards

## Maintenance
- At the end of any session that restructures the codebase, update the Structure section above to reflect the changes
- Do not modify the Documentation Index, Jira Board, Guidance, or Maintenance sections unless explicitly asked
