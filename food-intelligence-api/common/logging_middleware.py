import time
import logging
import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs", "requests")
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("datanest.requests")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(
        os.path.join(LOG_DIR, "requests.log"), encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s\t%(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(handler)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

        user = request.headers.get("x-rapidapi-user", "-")
        sub = request.headers.get("x-rapidapi-subscription", "-")
        method = request.method
        path = request.url.path
        query = str(request.url.query)[:200] if request.url.query else ""
        status = response.status_code

        logger.info(
            f"{method}\t{path}\t{query}\t{status}\t{elapsed_ms}ms\t"
            f"user={user}\tsub={sub}"
        )

        response.headers["X-Response-Time"] = f"{elapsed_ms}ms"
        return response
