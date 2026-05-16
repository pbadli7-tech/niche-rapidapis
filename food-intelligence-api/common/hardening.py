"""
Drop-in hardening for any FastAPI app.
Usage:
    from hardening import harden
    harden(app)
"""
import time
import logging
import os
from functools import lru_cache
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


def harden(app, log_dir=None, cache_ttl=300):
    """Add request logging, response timing headers, and standard error handlers."""
    if log_dir is None:
        log_dir = os.path.join(os.path.dirname(os.path.abspath(".")), "logs")
    os.makedirs(log_dir, exist_ok=True)

    req_logger = logging.getLogger("api.requests")
    if not req_logger.handlers:
        req_logger.setLevel(logging.INFO)
        fh = logging.FileHandler(os.path.join(log_dir, "requests.log"), encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s\t%(message)s"))
        req_logger.addHandler(fh)

    class _LoggingMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            start = time.perf_counter()
            response = await call_next(request)
            ms = round((time.perf_counter() - start) * 1000, 1)
            user = request.headers.get("x-rapidapi-user", "-")
            sub = request.headers.get("x-rapidapi-subscription", "-")
            req_logger.info(
                f"{request.method}\t{request.url.path}\t"
                f"{str(request.url.query)[:200]}\t{response.status_code}\t"
                f"{ms}ms\tuser={user}\tsub={sub}"
            )
            response.headers["X-Response-Time"] = f"{ms}ms"
            response.headers["X-Powered-By"] = "DataNest"
            return response

    app.add_middleware(_LoggingMiddleware)

    @app.exception_handler(400)
    async def bad_request(request, exc):
        return JSONResponse(status_code=400, content={
            "error": "Bad Request",
            "message": str(exc.detail) if hasattr(exc, "detail") else str(exc),
            "status_code": 400
        })

    @app.exception_handler(404)
    async def not_found(request, exc):
        return JSONResponse(status_code=404, content={
            "error": "Not Found",
            "message": str(exc.detail) if hasattr(exc, "detail") else "Resource not found",
            "status_code": 404
        })

    @app.exception_handler(429)
    async def rate_limited(request, exc):
        return JSONResponse(status_code=429, content={
            "error": "Rate Limited",
            "message": "Too many requests. Please slow down.",
            "status_code": 429
        })

    @app.exception_handler(500)
    async def server_error(request, exc):
        return JSONResponse(status_code=500, content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred. Please try again later.",
            "status_code": 500
        })


class SimpleCache:
    """Lightweight in-memory TTL cache for API responses."""
    def __init__(self, maxsize=500, default_ttl=300):
        self._store = {}
        self._maxsize = maxsize
        self._default_ttl = default_ttl

    def get(self, key):
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires = entry
        if time.time() > expires:
            del self._store[key]
            return None
        return value

    def set(self, key, value, ttl=None):
        if len(self._store) >= self._maxsize:
            now = time.time()
            expired = [k for k, (_, e) in self._store.items() if e < now]
            for k in expired:
                del self._store[k]
            if len(self._store) >= self._maxsize:
                oldest = min(self._store, key=lambda k: self._store[k][1])
                del self._store[oldest]
        self._store[key] = (value, time.time() + (ttl or self._default_ttl))
