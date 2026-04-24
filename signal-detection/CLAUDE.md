# signal-detection

Part of the [ocn monorepo](../CLAUDE.md).

## Overview

`signal-detection` is a FastAPI service (port 8002) that classifies news articles as **Signal**, **Weak Signal**, or **Noise** using vector similarity against a rolling reference corpus stored in Qdrant. It is a downstream consumer of `news-retrieval` — it never ingests articles directly.

The corpus is bootstrapped via a CLI command that fetches historical articles from `news-retrieval`, embeds them with `text-embedding-3-large` (via OpenRouter), clusters them into topic groups with MiniBatchKMeans, and writes `topic_clusters` + `corpus_centroids` rows to Postgres.

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
│   ├── __main__.py          Entry point (Click group: serve, bootstrap, promote-corpus)
│   ├── app.py               FastAPI factory
│   ├── auth.py              Bearer token validation
│   ├── db.py                DB infrastructure (psycopg2, init_db)
│   ├── seed.py              Seed classification_statuses
│   ├── controllers/
│   │   ├── classify.py      Classification job orchestration
│   │   ├── bootstrap.py     Corpus bootstrap pipeline
│   │   └── promote.py       Nightly deferred corpus promotion job
│   ├── models/
│   │   ├── jobs.py          classification_jobs / classifications / deferred_promotions repository
│   │   └── clusters.py      topic_clusters / corpus_centroids repository (incl. EWMA update)
│   └── routes/
│       ├── health.py        GET /health
│       └── classify.py      POST /classify, GET /classifications/*
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
