"""FastAPI app factory for lucky-clarke."""
from fastapi import FastAPI

from routes.a2a import router as a2a_router
from routes.health import router as health_router
from routes.webhooks import router as webhooks_router


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="lucky-clarke", version="1.0.0")
    app.include_router(health_router)
    app.include_router(a2a_router)
    app.include_router(webhooks_router)
    return app
