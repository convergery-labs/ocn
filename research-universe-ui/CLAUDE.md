# research-universe-ui

Standalone React SPA for the **AI Economy Universe** internal tool. Talks directly to the `research-universe` FastAPI backend via bearer token auth. Completely separate from the main `frontend/` service - different codebase, different deployment, different purpose.

Internal use only. 3–4 admin users.

---

## Stack

| Layer | Choice |
|-------|--------|
| Framework | React 18 + TypeScript |
| Build tool | Vite 5 |
| Styling | Tailwind CSS 3 |
| State | React `useState` / `useCallback` - no external store |
| HTTP | Native `fetch` with bearer token injection |
| Hosting (prod) | S3 + CloudFront |

---

## Features

### Chat tab
- Welcome screen with quick-start suggestion chips
- Sends messages to `POST /chat`, renders the agent's response
- Inline rich cards based on `card_type`:
  - `company_card` - verified company profile
  - `proposed_entry` - pending company profile with amber badge
  - `peer_proposals` - scrollable peer discovery list
  - `review_nudge` - count + link to Pending Review tab
- Typing indicator while waiting for the agent
- Conversation ID persisted for the session (agent remembers context)

### Pending Review tab
- Lists all companies with `status = 'pending_review'`
- Approve individual companies or bulk approve all
- Skeleton loaders, optimistic UI updates, toast feedback
- Badge on nav item shows live pending count

### Discovery tab - Run Scan
- Category selector grid (all 19 categories, select any subset)
- Triggers `POST /jobs/scan`, polls `GET /jobs/scan/{id}` every 5 s
- Live progress bar + per-category status (pending / scanning / done)
- Shows proposed + skipped counts per category

### Discovery tab - Schedule
- Shows `last_run_at` and `next_run_at` for the full sweep (from `GET /jobs/schedule`)
- CloudWatch runs a full 19-category scan twice a week (Monday + Thursday 09:00 UTC)
- No per-category rotation - every scheduled run covers all 19 categories

---

## Auth

API key entered in the sidebar, stored in `localStorage` under `ru_api_key`.  
All requests send `Authorization: Bearer <key>`.  
Key is validated against `GET /users/me` on load and after any change.

**Planned v2:** Google OAuth (backend issues a JWT; frontend stores it in place of the API key).  
Effort: ~7–8 hrs. Requires Google Cloud Console OAuth 2.0 credentials + a registered redirect URI.

---

## Security

| Control | How |
|---------|-----|
| No secrets in JS bundle | All config is runtime (`localStorage`) - nothing baked into the build |
| XSS via links | `safeUrl()` in `src/utils/url.ts` - only `http://` and `https://` URLs allowed in any `href`. `javascript:` and `data:` are silently dropped |
| Tabnapping | `rel="noreferrer noopener"` on every `target="_blank"` link |
| React rendering | JSX auto-escapes all values - no `dangerouslySetInnerHTML` anywhere in the codebase |
| Sensitive data logging | No `console.log` of API keys or response data |
| HTTPS | CloudFront enforces HTTPS end-to-end in production |
| CORS | Backend only accepts requests from the `CORS_ORIGINS` value set in Secrets Manager (CloudFront domain) |

---

## API it connects to

All requests go to the `research-universe` FastAPI service.

| Endpoint | Used by |
|----------|---------|
| `GET /users/me` | Auth verification on load |
| `POST /chat` | Chat tab |
| `GET /companies/pending` | Pending tab + badge count |
| `POST /companies/{id}/verify` | Approve button |
| `GET /taxonomy/categories` | Discovery category selector |
| `POST /jobs/scan` | Start scan |
| `GET /jobs/scan/{job_id}` | Poll scan progress |
| `GET /jobs/schedule` | Schedule tab |

API base URL defaults to `http://localhost:8007` (stored in `localStorage` under `ru_api_base`, editable in sidebar).

---

## Local dev

```bash
cd research-universe-ui
npm install
npm run dev
# open http://localhost:5173
```

Make sure the `research-universe` backend is running:
```bash
# from repo root
docker compose up research-universe
```

Then enter in the sidebar:
- **API URL**: `http://localhost:8007`
- **API Key**: generate one with `docker compose exec research-universe python -m src users create --name you`

---

## Build

```bash
npm run build   # tsc + vite build → dist/
```

`dist/` is a static site - upload to S3, serve via CloudFront. No server needed.

---

## Production deployment

Hosted on S3 + CloudFront (Terraform not yet written - next step after local validation).

After deploy, set `CORS_ORIGINS` in Secrets Manager (`ocn/staging/research-universe`) to the CloudFront distribution URL so the backend accepts requests from it.

---

## Maintenance

- No backend changes needed for purely UI changes
- API client is centralised in `src/api/client.ts` - add new endpoints there
- If the `research-universe` API adds new `card_type` values, add a renderer in `ChatTab.tsx → CardRenderer`
