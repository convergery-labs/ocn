# research-universe

Chat-first internal tool for maintaining the **AI Economy Universe** - a curated master list of ~1,003 companies across 19 categories and 8 infrastructure layers.

Internal use only. All users are admins (v1). 3–4 people initially.

---

## Source Data

The master taxonomy is derived from `AI_Economy_Universe_Final.xlsx` with four sheets:

| Sheet | Purpose |
|-------|---------|
| AI Economy Taxonomy | 8-layer stack architecture with subcategory tree |
| AI Economy Universe | ~1,003 companies - canonical data source |
| By Subcategory | Same companies, grouped by subcategory |
| Quantum Galaxy | Quantum-specific companies (public + private) |

### 8-Layer Stack
| Layer | Name |
|-------|------|
| 1 | Physical Foundation (Raw Materials, Energy) |
| 2 | Silicon & Manufacturing |
| 3 | Compute Hardware |
| 4 | Physical Infrastructure (Data Centers, Cooling, Networking, Telecom) |
| 5 | Cloud & Platform |
| 6 | Intelligence (AI Models) |
| 7 | Applications & Economy |
| 8 | Cross-Cutting Enablers (Cybersecurity, Sovereign AI, Finance, Water) |

### 19 Categories
| # | Category | Companies |
|---|----------|-----------|
| 01 | Raw Materials & Critical Minerals | 150 |
| 02 | Energy & Grid Infrastructure | 100 |
| 03 | Nuclear & Advanced Energy | 58 |
| 04 | Semiconductor Manufacturing | 181 |
| 05 | Compute Hardware & Edge Systems | 89 |
| 06 | Networking, Optical & Interconnect | 45 |
| 07 | Data Centers & Physical Infrastructure | 172 |
| 08 | Telecom & Connectivity | 22 |
| 09 | Cloud & Compute Platforms | 34 |
| 10 | AI Software Infrastructure | 186 |
| 11 | AI Data Infrastructure | 55 |
| 12 | AI Models & Intelligence Layer | 33 |
| 13 | Robotics & Physical AI | 32 |
| 14 | Quantum Computing & Sensing | 36 |
| 15 | Life Sciences & Healthcare AI | 88 |
| 16 | Defense, Aerospace & Sovereign AI | 34 |
| 17 | Financial Infrastructure & AI Capital | 51 |
| 18 | Water & Resource Infrastructure | 6 |
| 19 | Applications & Digital Economy | 166 |

---

## Database Tables

All tables live on the shared RDS PostgreSQL instance. The `pg_trgm` extension is enabled for fuzzy search.

### `universe_taxonomy`
Canonical list of all categories and subcategories. Single source of truth - companies reference this via FK arrays.

| Column | Type | Notes |
|--------|------|-------|
| `id` | serial PK | |
| `type` | text | `category` \| `subcategory` |
| `name` | text | unique per type |
| `parent_id` | integer FK | null for categories; points to category row for subcategories |
| `agent_proposed` | bool | true if created by the agent |
| `created_by` | text | user_name |
| `created_at` | timestamptz | |

### `universe_companies`
One row per company. A company that spans multiple categories stores all category/subcategory IDs as arrays on the same row.

| Column | Type | Notes |
|--------|------|-------|
| `id` | uuid PK | `gen_random_uuid()` |
| `company_name` | text UNIQUE | uniqueness constraint - one record per company |
| `ticker` | text | exchange-suffixed for international (e.g. `6971.T`, `000063.SZ`) |
| `market` | text | `National (US)` \| `International` |
| `country` | text | |
| `website` | text | |
| `category_ids` | integer[] | FK refs to `universe_taxonomy` (type=category); usually length 1 |
| `subcategory_ids` | integer[] | FK refs to `universe_taxonomy` (type=subcategory); aligns with category_ids |
| `multi_category_reason` | text | Claude-generated; only populated when `category_ids` has >1 entry |
| `status` | text | `pending_review` \| `verified` |
| `agent_added` | bool | true if created or edited via agent |
| `added_by` | text | user_name (user_id once Google Auth lands) |
| `added_at` | timestamptz | |
| `verified_by` | text | null until verified |
| `verified_at` | timestamptz | null until verified |

**Status semantics:**
- `pending_review` - agent has written the entry; awaits human confirmation
- `verified` - a user has confirmed the entry (seeded data starts as `verified`)

Downstream consumers (reports, simulations) should filter on `status = 'verified'` for high-stakes use.

**Indexes:** `gin(company_name gin_trgm_ops)` for fuzzy search; `ticker`, `status`, `agent_added`.

### `universe_conversations`
Persisted chat history per user session.

| Column | Type | Notes |
|--------|------|-------|
| `id` | uuid PK | |
| `user_id` | text | |
| `messages` | jsonb | full conversation history array |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

---

## Features

### Feature 1: Company Lookup

1. User types a company name in the chat interface
2. Agent performs a fuzzy match against the master DB
3. **Found** → shows the company's full profile card; offers to answer questions
4. **Not found** → agent responds: *"[Company] isn't in the universe yet. Want me to add it?"*

---

### Feature 2: Agent-Driven Company Addition

Triggered when user approves addition of a not-found company.

1. Agent uses Claude's knowledge to research and pre-fill all fields
2. Entry is **immediately written to DB** with:
   - `status = 'pending_review'`
   - `agent_added = true`
   - `added_by = <current user>`
3. Agent shows a **review card** of what was just added
4. Agent shows a nudge: *"Here's what I added - want to change anything?"*
5. User can chat to edit any field → agent updates the DB record in real-time
6. User clicks **[Looks Good]** → `status` flips to `verified`, `verified_by` and `verified_at` are set

Admins can see a **pending review queue**: *"X entries awaiting your review"* surfaced in the UI.

---

### Feature 3: Taxonomy Extension (New Subcategory / Category)

When a user proposes a new subcategory:

1. Agent runs a **fuzzy similarity check** against all existing subcategories
2. **Close match found** → agent asks: *"We already have 'OSS Models' - use that, or create 'Open Source LLMs' as a distinct entry?"*
3. **No match** → agent creates the new subcategory immediately
4. New taxonomy entries are flagged `agent_proposed = true`

Same flow applies to new category proposals. This prevents taxonomy drift as multiple admins add similar names independently.

---

### Feature 4: Peer Discovery (Gap Analysis)

Triggered automatically after every new company addition.

**Step A - Gap analysis**
Agent explains why the company wasn't already in the universe:
- New/emerging company
- Geographic blind spot
- Niche subcategory not yet represented
- Oversight in original curation

**Step B - Peer scan**
In the same Category + Subcategory, agent finds peer companies from the same and similar countries that should be in the universe but aren't.

**Step C - Approval** (two options, both available)
- **Individual:** user reviews each peer, approves/rejects/edits one at a time
- **Batch:** user approves the full proposed list at once

All approved peers are written to DB with `agent_added = true`, `status = 'pending_review'`.

---

### Feature 5: Universe Discovery Job

A background job triggered manually via a button in the Lovable UI (`POST /jobs/scan`). Proactively keeps the universe current without requiring any human discovery effort.

**What it does:**
1. Loops through all 19 categories sequentially
2. For each category - runs the sector research prompt, Claude returns a structured list of companies it knows globally across all major exchanges (NYSE, Nasdaq, LSE, TSE, HKEX, KRX, ASX, NSE, Euronext, Frankfurt, Shanghai/Shenzhen)
3. For each returned company - fuzzy-checks against the DB
4. **Not in universe** → writes as `agent_added=true`, `status=pending_review`
5. **Already exists** → skips (duplicate)
6. Returns a job summary: categories scanned, companies proposed, companies skipped as duplicates

**Admins review the pending queue after the job completes.** The pending review queue (Feature 2) is the primary review surface - the discovery job feeds it, humans drain it.

**Research prompt rules (per category):**
- Global scope: all major exchanges + notable private companies
- Minimum 50 companies per category, target 80–150
- Verified tickers only (real, currently trading)
- Exclude: acquired, dissolved, delisted, bankrupt
- Exclude: peripheral connections (only direct revenue-generating relationships)
- Systematic geography: US → Europe → Asia-Pacific → Rest of World
- Each company returned with: name, ticker, public/private, country, market, website, one-line description, proposed subcategory

**Endpoint:** `POST /jobs/scan`
- Optional body: `{ "categories": [7, 12] }` - scan specific categories only; omit to scan all 19
- Returns: `{ "job_id": "uuid", "status": "running" }` immediately (async)
- Progress: `GET /jobs/{job_id}` - returns per-category counts and overall status
- UI polls this endpoint to update the progress indicator

**Schedule:** CloudWatch EventBridge runs a full 19-category scan every 15 days at 09:00 UTC. No per-category rotation - each run always covers all 19.
- `GET /jobs/schedule` returns `{ last_run_at, next_run_at }` where `next_run_at = last_run_at + 15 days`
- The manual "Run Scan" button in the UI remains available for ad-hoc runs at any time

**Differs from `find_peers`:**

| | `find_peers` | Discovery Job |
|--|-------------|----------------|
| Trigger | User adds a company | Manual button in Lovable |
| Scope | One subcategory | All 19 categories |
| Output | 5–20 candidates | 50–300 candidates |
| Purpose | Fill the immediate gap | Keep whole universe current |

---

## Architecture & Deployment

### What runs on AWS
```
research-universe-ui  (S3 + CloudFront - see research-universe-ui/CLAUDE.md)
        ↕ HTTPS
    AWS ALB  (existing)
        ↕ /universe/* path prefix
    ECS Task: research-universe   ← FastAPI + Claude agent
        ↕
    RDS PostgreSQL  (existing instance, new tables)
        ↕
    OpenRouter API  (outbound - Claude tool-use calls)
```

### API Endpoints
```
GET  /health

POST /chat                          { message, conversation_id?, user_id, user_name }

GET  /companies/search?q=&limit=    fuzzy match on name + ticker (pg_trgm)
GET  /companies/{id}
POST /companies
PATCH /companies/{id}
POST /companies/{id}/verify
GET  /companies/pending

GET  /taxonomy/categories
GET  /taxonomy/subcategories?category_id=
GET  /taxonomy/search?q=            dedup check before creating new subcategory
POST /taxonomy/subcategories
POST /taxonomy/categories

# Discovery Job
POST /jobs/scan                     { "categories": [1,2,...] }  - omit for all 19
GET  /jobs/{job_id}                 progress + per-category counts
```

### Chat Response Envelope
Every `/chat` response returns this shape - the frontend reads `card_type` to render the right component:
```json
{
  "message": "...",
  "card_type": "company_card | proposed_entry | peer_proposals | review_nudge | null",
  "card_data": {},
  "conversation_id": "uuid"
}
```

### Agent Tools
| Tool | Purpose |
|------|---------|
| `search_companies(query)` | pg_trgm fuzzy search on name + ticker |
| `get_company(id)` | full profile |
| `create_company(fields)` | writes entry - `agent_added=true`, `status=pending_review` |
| `update_company(id, fields)` | edit any field |
| `verify_company(id)` | flip to `verified` |
| `list_pending()` | review queue |
| `search_taxonomy(query)` | fuzzy match before creating new subcategory |
| `create_taxonomy_entry(name, type, parent)` | add subcategory or category |
| `find_peers(category, subcategory, country)` | calls `search_companies` first, then proposes companies NOT already in DB |

### Auth
| Phase | Approach |
|-------|---------|
| v1 (now) | Email + password login (`POST /auth/login`) issues a session token. API keys (`ru_` prefix) still supported via `Authorization: Bearer <key>`. Users created via CLI (`python -m src users create`); passwords set via `python -m src users set-password`. |
| v2 | Google OAuth restricted to company domain; backend issues a short-lived JWT; ~7–8 hrs effort |

### Misspelling Handling
Three layers applied in sequence:
1. Claude pre-normalises obvious typos before hitting the DB
2. `pg_trgm` fuzzy search returns top 3 candidates with similarity scores
3. Confidence thresholds: >0.7 → show profile directly; 0.35–0.7 → ask "Did you mean X?"; <0.35 → treat as not found

### Data Seed
`src/seed.py` imports `AI_Economy_Universe_Final.xlsx` → DB in two passes:
- Pass 1: populate `universe_taxonomy` (categories then subcategories)
- Pass 2: group rows by `company_name`, call Claude for `multi_category_reason` on the 5 multi-category companies, insert `universe_companies`
- Seeded companies start with `status = 'verified'`, `agent_added = false`
- Errors written to `seed_errors.log`; script prints inserted/skipped summary

---

## Out of Scope (v1)

- Role-based access control (all users are admins)
- External financial data APIs (Yahoo Finance, Bloomberg, etc.)
- Web scraping for company research (Claude knowledge only)
- Read-only user accounts
- Public-facing access
