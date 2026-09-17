"""FastAPI application factory."""
from fastapi import FastAPI

from routes import health, jobs, run, webhooks


def create_app() -> FastAPI:
    """Create and return the configured FastAPI application."""
    application = FastAPI(title="Signal Detection Agent")
    application.include_router(health.router)
    application.include_router(run.router)
    application.include_router(jobs.router)
    application.include_router(webhooks.router)
    return application


app = create_app()
