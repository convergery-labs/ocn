# frontend

Do not load all documentation upfront. Read the index below,
identify which docs are relevant to your current task, and
read only those.

## Documentation Index

| Doc | Read when | Page ID |
| --- | --- | --- |
| [Technical Specification — frontend](https://opengrowthventures.atlassian.net/wiki/spaces/Projects/pages/92831747/Technical+Specification+frontend) | Making architectural or technical decisions about routing, auth, or state management | 92831747 |

Confluence space: `Projects` — Cloud: `opengrowthventures.atlassian.net`

## Structure

See [STRUCTURE.md](STRUCTURE.md) for the full directory layout.

## Guidance

- No container rebuild needed for dev — `npm run dev` uses Vite HMR; just save and the browser updates
- JWT is stored under `localStorage` key `ocn_token`; `AuthContext` is the single source of truth in the component tree
- Server data (articles, categories) belongs in TanStack Query hooks under `src/hooks/`, not in component state
- Pages should never import `src/api/client.ts` directly — use hooks
- `@/` is a path alias for `src/` — use it for all intra-project imports

## Maintenance

- When adding a route, update `App.tsx`, `STRUCTURE.md`, and the tech spec (page 92831747)
- When adding a hook, place it under `src/hooks/` following the `useResourceName` naming convention
- Do not modify the Documentation Index, Guidance, or Maintenance sections unless explicitly asked
