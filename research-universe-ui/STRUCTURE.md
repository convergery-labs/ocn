# research-universe-ui - Structure

```
research-universe-ui/
├── CLAUDE.md              Full documentation - stack, features, auth, security, API reference
├── STRUCTURE.md           This file
├── .gitignore             Excludes node_modules/, dist/, .env*
├── package.json           React 18, Vite 5, Tailwind 3, TypeScript
├── vite.config.ts         Vite + React plugin
├── tsconfig.json          Strict TypeScript config
├── tailwind.config.js     Custom animations: typing-bounce, fade-up, slide-in
├── postcss.config.js      Tailwind + autoprefixer
├── index.html             HTML shell - loads Inter font, mounts #root
└── src/
    ├── main.tsx           React root - mounts <App /> in StrictMode
    ├── index.css          Tailwind directives, custom scrollbar, typing-dot delays
    ├── types.ts           Shared TypeScript interfaces: User, Company, ChatMessage,
    │                        ScanJob, ScheduleEntry, Category, Tab
    ├── App.tsx            Root component - global state (user, pendingCount, activeTab),
    │                        auth verification on load, tab routing
    ├── api/
    │   └── client.ts      Centralised API wrapper - all fetch calls, Bearer token injection,
    │                        getApiKey/setApiKey, getApiBase/setApiBase (localStorage)
    ├── utils/
    │   └── url.ts         safeUrl() - strips javascript:/data: protocol links (XSS guard)
    └── components/
        ├── LoginScreen.tsx Email + password login form → POST /auth/login → session token
        ├── Sidebar.tsx    Top nav bar - brand, tab links, pending badge, account pill + dropdown
        ├── ChatTab.tsx    Chat interface - constellation backdrop, message thread, typing indicator,
        │                    card rendering. Sub-components: MessageRow, CompanyCard,
        │                    PeerProposals, ReviewNudge
        ├── PendingTab.tsx Pending review queue - skeleton loading, per-card approve,
        │                    bulk approve-all with progress, toast notifications
        └── DiscoveryTab.tsx   Two sub-tabs:
                               • Run Scan - category grid, start scan, live progress bar,
                                 per-category status (pending/running/done)
                               • Schedule - last_run_at / next_run_at (every 15 days)
```

## Data flow

```
User submits email + password on LoginScreen
  → api.login() → POST /auth/login → session_token stored in localStorage
  → App.tsx calls api.me() to verify on load
  → on success: currentUser set, pendingCount refreshed

Chat tab:
  User message → api.chat() → POST /chat
    → response: { message, card_type, card_data, conversation_id }
    → CardRenderer picks the right card component based on card_type

Pending tab:
  Load → api.pending() → GET /companies/pending
  Approve → api.verify(id) → POST /companies/{id}/verify
  → card removed, badge decremented

Discovery tab (scan):
  api.startScan(ids) → POST /jobs/scan → { job_id }
  setInterval 5s → api.pollScan(job_id) → GET /jobs/scan/{job_id}
  → updates progress bar + per-category status until status = completed|failed

Discovery tab (schedule):
  api.schedule() → GET /jobs/schedule → { last_run_at, next_run_at }
  → shows last run date + next run (last + 15 days)
```

## Key design decisions

| Decision | Reason |
|----------|--------|
| No router library | Single-page with 3 tabs - React state is sufficient |
| No global state library | Component-local state + prop callbacks cover all needs |
| `localStorage` for API key | Standard SPA bearer token pattern; same-origin only |
| `safeUrl()` on all hrefs | Prevents `javascript:` XSS from API-supplied website URLs |
| No `dangerouslySetInnerHTML` | React auto-escaping is the XSS defence; never bypass it |
| Polling (not WebSocket) | Scan jobs complete in minutes; 5 s poll is sufficient and simpler |
