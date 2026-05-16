import os
from fastapi import Header, HTTPException, Request
from typing import Optional


RAPIDAPI_PROXY_SECRET = os.getenv("RAPIDAPI_PROXY_SECRET", "")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


async def verify_rapidapi_request(
    request: Request,
    x_rapidapi_proxy_secret: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
):
    """
    Dual-mode auth:
    - On RapidAPI: validates X-RapidAPI-Proxy-Secret (set in RapidAPI dashboard)
    - Direct access: validates X-Api-Key for dev/testing
    Skip validation entirely when both env vars are unset (local dev).
    """
    if not RAPIDAPI_PROXY_SECRET and not INTERNAL_API_KEY:
        return  # local dev — no auth enforced

    if RAPIDAPI_PROXY_SECRET and x_rapidapi_proxy_secret == RAPIDAPI_PROXY_SECRET:
        return

    if INTERNAL_API_KEY and x_api_key == INTERNAL_API_KEY:
        return

    raise HTTPException(status_code=403, detail="Forbidden: invalid or missing API key")


async def get_api_key(
    x_rapidapi_user: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> str:
    """Return a caller identifier for logging / rate-limit bucketing."""
    return x_rapidapi_user or x_api_key or "anonymous"
