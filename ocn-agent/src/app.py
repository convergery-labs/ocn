"""FastAPI application factory."""
from fastapi import FastAPI

from routes import agent, health


def create_app() -> FastAPI:
    """Create and return the configured FastAPI application."""
    application = FastAPI(title="OCN Agent")
    application.include_router(health.router)
    application.include_router(agent.router)
    return application


app = create_app()
