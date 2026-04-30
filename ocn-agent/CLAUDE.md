# ocn-agent

Part of the [ocn monorepo](../CLAUDE.md).

## Overview

`ocn-agent` is a LangGraph-driven agent service that accepts natural-language
prompts, resolves them to a domain, fetches relevant articles from
`news-retrieval`, categorises and summarises them, and returns a structured
result. It is internal only — no ALB or public subnet.

## Jira Board
| Board | URL | Project Key |
|-------|-----|-------------|
| OCN Board | https://opengrowthventures.atlassian.net/jira/software/projects/CON/boards/34 | CON |

## Parent epic
CON-156 — LLM News Agent

## Structure

See [STRUCTURE.md](STRUCTURE.md) for descriptions.

```
ocn-agent/
├── Dockerfile
├── requirements.txt
├── .env.example
├── CLAUDE.md
├── STRUCTURE.md
├── README.md
└── src/
    ├── __main__.py           # Entry point: click + uvicorn.run (no DB init)
    ├── app.py                # FastAPI app factory; registers routers
    ├── state.py              # AgentState TypedDict
    ├── config.py             # Hardcoded domain config (slugs, descriptions, verticals)
    ├── clients/
    │   └── news_retrieval.py # Async httpx client for internal news-retrieval calls
    ├── graph/
    │   ├── __init__.py       # Exports compiled graph
    │   └── graph.py          # LangGraph StateGraph: nodes + topology
    └── routes/
        ├── health.py         # GET /health
        └── agent.py          # POST /agent/query, POST /agent/categorise (stubs)
```

## Guidance

- Domain config (slugs, descriptions, verticals) lives in `src/config.py` — no
  DB for configuration
- The graph topology is defined in `src/graph/graph.py`; node implementations
  live alongside it
- All upstream addresses and credentials come from env vars — never hardcode
- Use the Jira board (project key `CON`) to track and reference cards

## Maintenance

- Do not modify the Jira Board, Guidance, or Maintenance sections unless
  explicitly asked
- Update STRUCTURE.md and this file after adding new modules
