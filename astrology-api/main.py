"""
Astrology API by DataNest — deterministic daily/weekly/monthly horoscopes,
zodiac sign profiles, and sign compatibility. No external data source: every
reading is generated from a seed of (sign, period), so it is stable per day,
cache-friendly, and free to operate.

Endpoints
  GET /signs                          List all 12 zodiac signs
  GET /sign/{sign}                    Profile for one sign
  GET /sign-by-date?date=YYYY-MM-DD   Which sign a date falls under
  GET /horoscope/{sign}?day=today     Daily horoscope (today|tomorrow|yesterday)
  GET /weekly/{sign}                  This week's horoscope
  GET /monthly/{sign}                 This month's horoscope
  GET /compatibility/{a}/{b}          Compatibility between two signs
  GET /daily-all?day=today            Daily horoscope for ALL 12 signs (dashboard)
"""
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from common.auth import verify_rapidapi_request
from common.logging_middleware import RequestLoggingMiddleware
from common.cache import TTLCache
from common.response import success
import engine
import content
import astro_calc
import cities as cities_db


def _to_utc(date_str: str, time_str: str, tz: str | None, tz_offset: float | None) -> datetime:
    """Combine local birth date+time into a UTC datetime.

    Accepts an IANA `tz` (e.g. 'Europe/London', handles historical DST) or a
    fixed `tz_offset` in hours east of UTC. Falls back to treating input as UTC.
    """
    try:
        y, m, d = (int(x) for x in date_str.split("-"))
        hh, mm = (int(x) for x in time_str.split(":")[:2])
    except Exception:
        raise HTTPException(400, "date must be YYYY-MM-DD and time HH:MM")
    if tz:
        try:
            from zoneinfo import ZoneInfo
            local = datetime(y, m, d, hh, mm, tzinfo=ZoneInfo(tz))
            return local.astimezone(timezone.utc)
        except Exception:
            pass
    if tz_offset is not None:
        return (datetime(y, m, d, hh, mm) - timedelta(hours=tz_offset)).replace(tzinfo=timezone.utc)
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)

_cache = TTLCache(maxsize=2000, ttl=3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the AI content cache on startup (in a background thread so it never
    # blocks readiness). This makes content self-heal after every restart/redeploy
    # even without a persistent volume — daily + weekly are the most-viewed.
    import threading

    def _warm():
        try:
            content.prewarm(["daily", "weekly"])
        except Exception:
            pass

    threading.Thread(target=_warm, daemon=True).start()
    yield


app = FastAPI(
    title="Astrology API by DataNest",
    version="1.0.0",
    description="Daily, weekly and monthly horoscopes, zodiac sign profiles "
                "and compatibility — clean JSON, no key juggling.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
app.add_middleware(RequestLoggingMiddleware)

_AUTH = [Depends(verify_rapidapi_request)]


@app.get("/", include_in_schema=False)
async def root():
    return {"api": "Astrology API by DataNest", "version": "1.0.0", "docs": "/docs"}


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


# ── Engagement (public: called directly from getmyhoro.com browsers) ──
import engage
from pydantic import BaseModel


class MoodVote(BaseModel):
    sign: str
    mood: str


class RatingVote(BaseModel):
    sign: str
    period: str
    key: str
    stars: int


@app.post("/engage/mood", summary="Vote today's cosmic mood")
async def engage_mood_vote(v: MoodVote):
    try:
        return {"status": "success", "data": engage.vote_mood(v.sign, v.mood)}
    except ValueError as e:
        return {"status": "error", "message": str(e)}


@app.get("/engage/mood", summary="Today's cosmic mood results")
async def engage_mood_get(date: str | None = None):
    return {"status": "success", "data": engage.mood_results(date)}


@app.post("/engage/rating", summary="Rate a horoscope reading 1-5")
async def engage_rating_vote(v: RatingVote):
    try:
        return {"status": "success", "data": engage.add_rating(v.sign, v.period, v.key, v.stars)}
    except ValueError as e:
        return {"status": "error", "message": str(e)}


@app.get("/engage/rating", summary="Aggregate rating for a reading")
async def engage_rating_get(sign: str, period: str, key: str):
    return {"status": "success", "data": engage.get_rating(sign, period, key)}


@app.get("/signs", summary="List all 12 zodiac signs", dependencies=_AUTH)
async def signs():
    return success(engine.all_signs())


@app.get("/sign/{sign}", summary="Zodiac sign profile", dependencies=_AUTH)
async def sign_profile(sign: str):
    s = engine.get_sign(sign)
    if not s:
        raise HTTPException(404, f"Unknown sign '{sign}'")
    return success({k: s[k] for k in ("name", "symbol", "element", "modality",
                                      "ruling_planet", "date_range", "traits")})


@app.get("/sign-by-date", summary="Find the sign for a date", dependencies=_AUTH)
async def sign_by_date(
    date_str: str = Query(..., alias="date", description="YYYY-MM-DD"),
):
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    s = engine.sign_for_date(d)
    return success({"date": date_str, "sign": s["name"], "symbol": s["symbol"],
                    "element": s["element"], "date_range": s["date_range"]})


# NOTE: the content endpoints are plain `def` (not async) so FastAPI runs them
# in a worker threadpool. Content generation calls Claude over HTTP synchronously;
# running in a thread keeps one slow generation from blocking the whole event loop.
@app.get("/horoscope/{sign}", summary="Daily horoscope", dependencies=_AUTH)
def daily(
    sign: str,
    day: str = Query("today", pattern="^(today|tomorrow|yesterday)$"),
    date_str: str | None = Query(
        None, alias="date",
        description="Explicit date YYYY-MM-DD (overrides 'day'). Used for the "
                    "Monday→Sunday weekly view.",
    ),
    lite: bool = Query(False, description="Skip AI; return fast deterministic content "
                                          "(used for week-strip previews & dashboards)."),
):
    on_date = None
    if date_str:
        try:
            on_date = date.fromisoformat(date_str)
        except ValueError:
            raise HTTPException(400, "date must be YYYY-MM-DD")

    key = f"daily:{sign.lower()}:{date_str or day.lower()}:{int(lite)}"
    cached = _cache.get(key)
    if cached:
        return success(cached)
    resolved = on_date or engine._resolve_day(day)
    if lite:
        data = engine.daily_horoscope(sign, on_date=resolved)
    else:
        data = content.get_reading(sign, "daily", on_date=resolved)
    if not data:
        raise HTTPException(404, f"Unknown sign '{sign}'")
    _cache.set(key, data)
    return success(data)


@app.get("/weekly/{sign}", summary="Weekly horoscope", dependencies=_AUTH)
def weekly(sign: str):
    data = content.get_reading(sign, "weekly")
    if not data:
        raise HTTPException(404, f"Unknown sign '{sign}'")
    return success(data)


@app.get("/monthly/{sign}", summary="Monthly horoscope", dependencies=_AUTH)
def monthly(sign: str):
    data = content.get_reading(sign, "monthly")
    if not data:
        raise HTTPException(404, f"Unknown sign '{sign}'")
    return success(data)


@app.get("/yearly/{sign}", summary="Yearly horoscope", dependencies=_AUTH)
def yearly(sign: str):
    data = content.get_reading(sign, "yearly")
    if not data:
        raise HTTPException(404, f"Unknown sign '{sign}'")
    return success(data)


# ── Birth-chart tools ──────────────────────────────────────────────────
@app.get("/cities", summary="Birthplace search (autocomplete)", dependencies=_AUTH)
async def cities(q: str = Query(..., min_length=1), limit: int = Query(8, ge=1, le=20)):
    return success(cities_db.search(q, limit))


@app.get("/big-three", summary="Sun, Moon & Rising signs", dependencies=_AUTH)
async def big_three(
    date: str = Query(..., description="Birth date YYYY-MM-DD"),
    time: str = Query("12:00", description="Birth time HH:MM (local)"),
    lat: float | None = Query(None),
    lng: float | None = Query(None),
    tz: str | None = Query(None, description="IANA timezone, e.g. Europe/London"),
    tz_offset: float | None = Query(None, description="Hours east of UTC (if no tz)"),
):
    dt = _to_utc(date, time, tz, tz_offset)
    return success(astro_calc.big_three(dt, lat, lng))


class NatalRequest(BaseModel):
    date: str
    time: str = "12:00"
    lat: float | None = None
    lng: float | None = None
    tz: str | None = None
    tz_offset: float | None = None


@app.get("/prewarm", summary="Pre-generate AI content for all signs", dependencies=_AUTH)
def prewarm(periods: str = Query("daily,weekly,monthly,yearly")):
    """Call from a daily cron so the AI content cache is warm before users arrive."""
    return success(content.prewarm([p.strip() for p in periods.split(",") if p.strip()]))


@app.post("/natal", summary="Full natal (birth) chart", dependencies=_AUTH)
async def natal(req: NatalRequest):
    dt = _to_utc(req.date, req.time, req.tz, req.tz_offset)
    chart = astro_calc.compute_chart(dt, req.lat, req.lng)
    chart["input"] = {
        "date": req.date, "time": req.time,
        "lat": req.lat, "lng": req.lng,
        "utc": dt.isoformat(),
        "has_houses": req.lat is not None and req.lng is not None,
    }
    return success(chart)


@app.get("/compatibility/{sign_a}/{sign_b}",
         summary="Compatibility between two signs", dependencies=_AUTH)
async def compat(sign_a: str, sign_b: str):
    data = engine.compatibility(sign_a, sign_b)
    if not data:
        raise HTTPException(404, "Unknown sign in pair")
    return success(data)


@app.get("/daily-all", summary="Daily horoscope for all 12 signs",
         description="One call returns every sign's reading — built for dashboards.",
         dependencies=_AUTH)
def daily_all(
    day: str = Query("today", pattern="^(today|tomorrow|yesterday)$"),
    lite: bool = Query(True, description="Deterministic snippets (default) — the "
                                         "homepage shows previews, not full readings."),
):
    key = f"daily-all:{day.lower()}:{int(lite)}"
    cached = _cache.get(key)
    if cached:
        return success(cached)
    resolved = engine._resolve_day(day)
    if lite:
        out = [engine.daily_horoscope(s, on_date=resolved) for s in engine.SIGN_NAMES]
    else:
        out = [content.get_reading(s, "daily", on_date=resolved) for s in engine.SIGN_NAMES]
    payload = {"day": day.lower(), "date": out[0]["date"], "count": len(out),
               "signs": out}
    _cache.set(key, payload)
    return success(payload)
