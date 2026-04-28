"""Catch-all proxy routes for each upstream service."""
import os

from fastapi import APIRouter, Request
from fastapi.responses import Response

from proxy import forward_request

router = APIRouter()

_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]


@router.api_route("/auth/{path:path}", methods=_METHODS)
async def proxy_auth(path: str, request: Request) -> Response:
    """Proxy requests under /auth/* to the auth-service."""
    return await forward_request(
        os.environ.get("GATEWAY_AUTH_URL", ""), path, request
    )


@router.api_route("/news/{path:path}", methods=_METHODS)
async def proxy_news(path: str, request: Request) -> Response:
    """Proxy requests under /news/* to news-retrieval."""
    return await forward_request(
        os.environ.get("GATEWAY_NEWS_URL", ""), path, request
    )


@router.api_route("/signal/{path:path}", methods=_METHODS)
async def proxy_signal(path: str, request: Request) -> Response:
    """Proxy requests under /signal/* to signal-detection."""
    return await forward_request(
        os.environ.get("GATEWAY_SIGNAL_URL", ""), path, request
    )
