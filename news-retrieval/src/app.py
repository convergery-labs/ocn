"""FastAPI application factory."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import (
    articles,
    domains,
    frequencies,
    grants,
    health,
    run,
    runs,
    sources,
)


def create_app() -> FastAPI:
    """Create and return the configured FastAPI application."""
    application = FastAPI(title="News Aggregator")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(run.router)
    application.include_router(runs.router)
    application.include_router(articles.router)
    application.include_router(health.router)
    application.include_router(frequencies.router)
    application.include_router(domains.router)
    application.include_router(sources.router)
    application.include_router(grants.router)

    return application


app = create_app()
