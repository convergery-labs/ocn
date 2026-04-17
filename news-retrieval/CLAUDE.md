# news-retrieval

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
| news-retrieval Board | https://opengrowthventures.atlassian.net/jira/software/projects/CON/boards/34 | CON |

## Structure

See [STRUCTURE.md](STRUCTURE.md) for descriptions.

```
news-retrieval/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml        # pytest config (asyncio_mode=auto)
├── requirements-test.txt # test-only pip deps
├── README.md
├── CLAUDE.md
├── STRUCTURE.md
├── tests/                # automated test suite (pytest)
│   ├── conftest.py       # session/function fixtures (DB, keys, client)
│   ├── test_auth.py
│   ├── test_runs.py
│   ├── test_guard_chain.py
│   ├── test_pagination.py
│   ├── test_webhook.py
│   ├── test_ownership.py
│   └── test_pipeline.py
└── src/
    ├── __main__.py       # CLI entry point (uvicorn + click)
    ├── app.py            # FastAPI app factory
    ├── auth.py           # require_auth / require_admin FastAPI dependencies
    ├── pipeline.py       # Fetch + relevance filter pipeline (fetch → LLM title filter)
    ├── db.py             # PostgreSQL connection, _Connection wrapper, DuplicateError, schema init
    ├── seed.py           # Idempotent seed for run_statuses, frequencies, domains, sources, admin key
    ├── models/           # DB query functions (repository layer)
    │   ├── api_keys.py
    │   ├── articles.py
    │   ├── atomic.py
    │   ├── domains.py
    │   ├── frequencies.py
    │   ├── runs.py
    │   └── sources.py
    ├── controllers/      # Business logic and multi-step orchestration
    │   ├── domains.py
    │   └── run.py
    └── routes/           # Thin HTTP adapters (FastAPI APIRouters)
        ├── api_keys.py
        ├── articles.py
        ├── domains.py
        ├── frequencies.py
        ├── health.py
        ├── run.py
        ├── runs.py
        └── sources.py
```

## Guidance
- Read only the docs relevant to your task — not all of them
- Check the index above before asking for clarification; the answer is often in a doc
- When in doubt about scope or requirements, read the Functional Requirements or PRD first
- Use the Jira board (project key `CON`) to track and reference cards

## Maintenance
- At the end of any session that restructures the codebase, update the Structure section above to reflect the changes
- Do not modify the Documentation Index, Jira Board, Guidance, or Maintenance sections unless explicitly asked
