"""FastAPI application factory for auth-service."""
from fastapi import FastAPI

from routes import auth, health, jwks, keys, users, validate


def create_app() -> FastAPI:
    """Create and return the configured FastAPI application."""
    application = FastAPI(title="Auth Service")
    application.include_router(health.router)
    application.include_router(auth.router)
    application.include_router(jwks.router)
    application.include_router(keys.router)
    application.include_router(users.router)
    application.include_router(validate.router)
    return application


app = create_app()
