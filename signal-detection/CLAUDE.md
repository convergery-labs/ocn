# signal-detection

Part of the [ocn monorepo](../CLAUDE.md).

## Overview

`signal-detection` is a FastAPI service (port 8002) that classifies news articles as **Signal**, **Weak Signal**, or **Noise** using vector similarity against a rolling reference corpus stored in Qdrant. It is a downstream consumer of `news-retrieval` — it never ingests articles directly.

The corpus is bootstrapped via a CLI command that fetches historical articles from `news-retrieval`, embeds them with `text-embedding-3-large` (via OpenRouter), clusters them into topic groups with MiniBatchKMeans, and writes `topic_clusters` + `corpus_centroids` rows to Postgres.

Additional historical content can be ingested directly into Qdrant via the `historical-ingest` CLI (GDELT news and arXiv research papers), with no Postgres involvement.

After each classification, the article embedding incrementally updates the EWMA centroid for its assigned cluster. Signal articles are deferred for 30 days and re-evaluated by a nightly `promote-corpus` job before their centroid contribution is accepted.

## Documentation Index
| Doc | Read when | Page ID |
|-----|-----------|---------|
| [Project Brief](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/73203716/Project+Brief+—+signal-detection) | Understanding the service's purpose and goals | 73203716 |
| [Scope & Success Criteria](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/73629710/Scope+%26+Success+Criteria+—+signal-detection) | Defining or verifying acceptance criteria | 73629710 |
| [Functional Requirements](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/74153986/Functional+Requirements+—+signal-detection) | Implementing or questioning any feature | 74153986 |
| [Technical Specifications](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/74154013/Technical+Specifications+—+signal-detection) | Making architectural or technical decisions | 74154013 |
| [Solution Exploration](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/74416130/Solution+Exploration+—+signal-detection) | Evaluating design or approach options | 74416130 |
| [Evidence Base](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/75923457/Evidence+Base+—+signal-detection+Approach) | Validating or challenging the chosen approach | 75923457 |
| [Infrastructure Request](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/74940431/Infrastructure+Request+—+OCN+Signal+Detection+Platform) | Provisioning or configuring infrastructure | 74940431 |
| [Assumptions & Open Questions Log](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/73957390/Assumptions+%26+Open+Questions+Log+—+signal-detection) | Resolving ambiguities or open questions | 73957390 |

Confluence space: `Projects` — Cloud: `opengrowthventures.atlassian.net`

## Jira Board
| Board | URL | Project Key |
|-------|-----|-------------|
| OCN Board | https://opengrowthventures.atlassian.net/jira/software/projects/CON/boards/34 | CON |

## Structure

See [STRUCTURE.md](STRUCTURE.md) for descriptions.

```
signal-detection/
├── Dockerfile
├── requirements.txt
├── requirements-test.txt
├── pyproject.toml
├── src/
│   ├── __main__.py          Entry point (Click group: serve, bootstrap, promote-corpus,
│   │                                     historical-ingest)
│   ├── app.py               FastAPI factory
│   ├── auth.py              x-ocn-caller header extraction
│   ├── db.py                DB adapter — _new_connection(), init_db(); delegates
│   │                        connection pooling, get_db(), transaction(), and
│   │                        DuplicateError to shared/src/db_utils.py
│   ├── seed.py              Seed classification_statuses
│   ├── controllers/
│   │   ├── classify.py      Classification job orchestration
│   │   ├── bootstrap.py     Corpus bootstrap pipeline
│   │   └── promote.py       Nightly deferred corpus promotion job
│   ├── models/
│   │   ├── jobs.py          classification_jobs / classifications / deferred_promotions
│   │   ├── claims.py        claims
│   │   └── clusters.py      topic_clusters / corpus_centroids (incl. EWMA update)
│   ├── routes/
│   │   ├── health.py        GET /health
│   │   └── classify.py      POST /classify, GET /classifications/*
│   └── historical_ingestion/
│       ├── schema.py        HistoricalDocument dataclass
│       ├── pipeline.py      Orchestrator (fetch, deduplicate, embed, upsert)
│       └── adapters/
│           ├── base.py      AbstractHistoricalAdapter
│           ├── gdelt.py     GDELT 2.0 Doc API adapter
│           └── arxiv.py     arXiv Atom feed adapter
└── tests/
    ├── conftest.py
    ├── test_smoke.py
    └── test_classify.py
```

## Guidance

- Read only the docs relevant to your task
- Use the Jira board (project key `CON`) to track and reference cards

## Maintenance

- Do not modify the Jira Board, Guidance, or Maintenance sections unless explicitly asked
