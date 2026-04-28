"""FastAPI application factory for api-gateway."""
from fastapi import FastAPI

from routes import health, proxy_routes


def create_app() -> FastAPI:
    """Create and return the configured FastAPI application."""
    application = FastAPI(title="API Gateway")
    application.include_router(health.router)
    application.include_router(proxy_routes.router)
    return application


app = create_app()
