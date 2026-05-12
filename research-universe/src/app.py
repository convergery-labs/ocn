"""FastAPI app factory for research-universe."""
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="research-universe", version="1.0.0")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app
