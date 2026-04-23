"""FastAPI application factory."""
from fastapi import FastAPI

from routes import classify, health


def create_app() -> FastAPI:
    """Create and return the configured FastAPI application."""
    application = FastAPI(title="Signal Detection")
    application.include_router(health.router)
    application.include_router(classify.router)
    return application


app = create_app()
