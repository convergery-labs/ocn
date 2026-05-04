# frontend

Part of the [ocn monorepo](../README.md). See root README for full system setup.

React + TypeScript + Vite SPA for the OCN platform. Displays article feeds and domain categories for authenticated users.

## Local development

```bash
cd frontend
cp .env.example .env.local   # set VITE_API_BASE_URL
npm install
npm run dev                  # http://localhost:5173
```

The dev server proxies `/api` to `VITE_API_BASE_URL` (default `http://localhost:8004`), stripping the `/api` prefix before forwarding.

## Scripts

| Command | Description |
| --- | --- |
| `npm run dev` | Start Vite dev server with HMR |
| `npm run build` | Type-check and build to `dist/` |
| `npm run lint` | ESLint check |
| `npm run preview` | Serve the production build locally |

## Staging deployment

The SPA is hosted on S3 + CloudFront in `eu-north-1`. Pushing to `main` with
changes under `frontend/` triggers `.github/workflows/deploy-frontend.yml`,
which builds the app and syncs the `dist/` output to the S3 bucket, then
invalidates the CloudFront cache.

The staging URL is available as the `frontend_url` Terraform output in
`infra/staging/`. Three GitHub secrets must be set before the workflow can
run: `FRONTEND_BUCKET`, `CLOUDFRONT_DISTRIBUTION_ID`, and
`STAGING_API_BASE_URL` (the ALB DNS name).
