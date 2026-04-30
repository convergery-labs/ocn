"""FastAPI application factory for api-gateway."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import health, proxy_routes


def create_app() -> FastAPI:
    """Create and return the configured FastAPI application."""
    application = FastAPI(title="API Gateway")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_methods=['*'],
        allow_headers=['*'],
    )
    application.include_router(health.router)
    application.include_router(proxy_routes.router)
    return application


app = create_app()
