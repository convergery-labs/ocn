# frontend — Structure

```
frontend/
├── index.html                 Vite entry point
├── vite.config.ts             Path alias (@/ → src/), /api proxy (rewrites /api → /)
├── tsconfig.json              TypeScript config; paths mirror vite alias
├── tsconfig.node.json         TypeScript config for vite.config.ts itself
├── package.json
├── .eslintrc.cjs
├── .prettierrc
├── .env.example               Documents VITE_API_BASE_URL
└── src/
    ├── main.tsx               React root — mounts BrowserRouter, QueryClientProvider, AuthProvider
    ├── App.tsx                Route definitions (public + protected)
    ├── api/
    │   └── client.ts          Axios instance; request interceptor attaches JWT; 401 handler
    ├── components/
    │   └── ProtectedRoute.tsx Redirects to /login if no token in AuthContext
    ├── context/
    │   └── AuthContext.tsx    localStorage-backed auth state; exposes user, login(), logout()
    ├── hooks/
    │   ├── useDomains.ts      TanStack Query — GET /news/domains (public)
    │   ├── useLoginMutation.ts  TanStack useMutation — POST /auth/login
    │   └── useRegisterMutation.ts  TanStack useMutation — POST /auth/register
    └── pages/
        ├── LoginPage.tsx
        ├── RegisterPage.tsx
        └── ArticleGridPage.tsx
```

## Layer responsibilities

| Layer | Owns |
| --- | --- |
| `api/client.ts` | HTTP transport; JWT attachment; 401 redirect |
| `context/AuthContext` | Auth state; localStorage read/write |
| `hooks/` | TanStack Query hooks; cache keys; stale-time config |
| `pages/` | Route-level components; compose hooks + UI; never import `client` directly |
| `components/ProtectedRoute` | Auth gate for protected routes |
