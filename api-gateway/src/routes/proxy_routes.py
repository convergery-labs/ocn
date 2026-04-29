"""Catch-all proxy routes for each upstream service."""
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from auth import require_admin, require_auth
from proxy import forward_request

router = APIRouter()

_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]


@router.api_route("/auth/login", methods=_METHODS)
async def proxy_auth_login(request: Request) -> Response:
    """Proxy /auth/login to the auth-service (public — no auth)."""
    return await forward_request(
        os.environ.get("GATEWAY_AUTH_URL", ""), "login", request
    )


@router.api_route("/auth/register", methods=_METHODS)
async def proxy_auth_register(request: Request) -> Response:
    """Proxy /auth/register to the auth-service (public — no auth)."""
    return await forward_request(
        os.environ.get("GATEWAY_AUTH_URL", ""), "register", request
    )


@router.api_route("/auth/jwks", methods=_METHODS)
async def proxy_auth_jwks(request: Request) -> Response:
    """Proxy /auth/jwks to the auth-service (public — no auth)."""
    return await forward_request(
        os.environ.get("GATEWAY_AUTH_URL", ""), "jwks", request
    )


@router.api_route("/auth/{path:path}", methods=_METHODS)
async def proxy_auth(
    path: str,
    request: Request,
    caller: dict[str, Any] = Depends(require_auth),
) -> Response:
    """Proxy requests under /auth/* to the auth-service."""
    return await forward_request(
        os.environ.get("GATEWAY_AUTH_URL", ""), path, request, caller
    )


@router.post("/news/run")
async def proxy_news_run(
    request: Request,
    caller: dict[str, Any] = Depends(require_auth),
) -> Response:
    """Proxy POST /news/run with domain scoping for JWT callers.

    JWT callers without the admin role are rejected with 403 if the
    requested domain is not in their token's ``domains`` claim.
    """
    if caller["auth_type"] == "jwt" and caller["role"] != "admin":
        body = await request.json()
        domain = body.get("domain", "")
        if domain not in caller["domains"]:
            raise HTTPException(
                status_code=403,
                detail="Domain not in your authorized domains.",
            )
    return await forward_request(
        os.environ.get("GATEWAY_NEWS_URL", ""), "run", request, caller
    )


@router.api_route("/news/{path:path}", methods=_METHODS)
async def proxy_news(
    path: str,
    request: Request,
    caller: dict[str, Any] = Depends(require_auth),
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
