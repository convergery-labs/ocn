"""FastAPI application factory."""
from fastapi import FastAPI

from routes import health


def create_app() -> FastAPI:
    """Create and return the configured FastAPI application."""
    application = FastAPI(title="Signal Detection")
    application.include_router(health.router)
    return application


app = create_app()
