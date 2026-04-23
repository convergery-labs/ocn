"""Smoke test: verify the application can be imported and created."""
from fastapi import FastAPI

from app import create_app


def test_app_created() -> None:
    """App factory returns a configured FastAPI instance."""
    application = create_app()
    assert isinstance(application, FastAPI)
    routes = [r.path for r in application.routes]
    assert "/health" in routes
