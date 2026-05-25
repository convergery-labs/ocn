"""Catch-all proxy routes for each upstream service."""
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from auth import optional_auth, require_admin
from proxy import forward_request

router = APIRouter()

_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]


@router.api_route("/auth/{path:path}", methods=_METHODS)
async def proxy_auth(
    path: str,
    request: Request,
    caller: Optional[dict[str, Any]] = Depends(optional_auth),
) -> Response:
    """Proxy requests under /auth/* to the auth-service."""
    return await forward_request(
        os.environ.get("GATEWAY_AUTH_URL", ""), path, request, caller
    )


@router.api_route("/news/{path:path}", methods=_METHODS)
async def proxy_news(
    path: str,
    request: Request,
    caller: Optional[dict[str, Any]] = Depends(optional_auth),
) -> Response:
    """Proxy requests under /news/* to news-retrieval."""
    return await forward_request(
        os.environ.get("GATEWAY_NEWS_URL", ""), path, request, caller
    )


@router.api_route("/signal/{path:path}", methods=_METHODS)
async def proxy_signal(
    path: str,
    request: Request,
    caller: dict[str, Any] = Depends(require_admin),
) -> Response:
    """Proxy requests under /signal/* to signal-detection (admin only)."""
    return await forward_request(
        os.environ.get("GATEWAY_SIGNAL_URL", ""), path, request, caller
    )


@router.api_route("/agent/{path:path}", methods=_METHODS)
async def proxy_signal_agent(
    path: str,
    request: Request,
    caller: Optional[dict[str, Any]] = Depends(optional_auth),
) -> Response:
    """Proxy requests under /agent/* to signal-detection-agent."""
    return await forward_request(
        os.environ.get("GATEWAY_SIGNAL_AGENT_URL", ""), path, request, caller
    )
