"""FastAPI app factory for research-universe."""
import db
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

import config
from auth import get_current_user
from limiter import limiter  # noqa: F401 - re-exported for routes
from routes.auth import router as auth_router
from routes.chat import router as chat_router
from routes.companies import router as companies_router
from routes.health import router as health_router
from routes.jobs import router as jobs_router
from routes.taxonomy import router as taxonomy_router
from routes.users import router as users_router

def create_app() -> FastAPI:
    db.init_db()

    app = FastAPI(title="research-universe", version="1.0.0")
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Strip ALB path prefix (e.g. /universe/chat → /chat) in production.
    # Transparent when API_PREFIX is empty (local dev).
    if config.API_PREFIX:
        class StripPrefixMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):
                if request.url.path.startswith(config.API_PREFIX):
                    request.scope["path"] = request.scope["path"][len(config.API_PREFIX):] or "/"
                return await call_next(request)
        app.add_middleware(StripPrefixMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Public routes (no auth) ──────────────────────────────────────────
    app.include_router(health_router)
    app.include_router(auth_router)

    # ── Protected routes (require valid bearer token) ────────────────────
    protected = {"dependencies": [Depends(get_current_user)]}

    app.include_router(chat_router, **protected)
    app.include_router(companies_router, **protected)
    app.include_router(taxonomy_router, **protected)
    app.include_router(jobs_router, **protected)
    app.include_router(users_router)   # users routes handle their own auth via Depends

    return app
