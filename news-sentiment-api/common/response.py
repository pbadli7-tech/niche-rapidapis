from typing import Any, Optional
import time


def success(data: Any, meta: Optional[dict] = None) -> dict:
    out = {"status": "success", "data": data, "timestamp": int(time.time())}
    if meta:
        out["meta"] = meta
    return out


def error(message: str, code: int = 400, details: Any = None) -> dict:
    out = {"status": "error", "message": message, "code": code, "timestamp": int(time.time())}
    if details:
        out["details"] = details
    return out


def paginate(data: list, page: int, per_page: int, total: int) -> dict:
    return success(
        data,
        meta={
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (total + per_page - 1) // per_page,
        },
    )
