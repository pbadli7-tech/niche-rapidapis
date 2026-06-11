#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Engagement store — community mood votes + horoscope-accuracy ratings for
getmyhoro.com. SQLite, no external services. Endpoints are public (browser
calls them directly) but accept only whitelisted values, so there is nothing
to abuse beyond ordinary ballot-stuffing — acceptable for a fun meter.

Note: on Railway's ephemeral filesystem the DB resets on redeploys. Mood data
is daily anyway; rating aggregates restart on deploy — fine for a vibe meter.
Attach a Railway volume and set ENGAGE_DB to persist forever.
"""
import os, sqlite3, threading
from datetime import datetime, timezone

_DB = os.getenv("ENGAGE_DB", "engage.db")
_lock = threading.Lock()

MOODS = {"fire", "peaceful", "introspective", "frustrated", "chaotic"}
SIGNS = {"aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra",
         "scorpio", "sagittarius", "capricorn", "aquarius", "pisces"}
PERIODS = {"daily", "weekly", "monthly"}


def _conn():
    c = sqlite3.connect(_DB, timeout=10)
    c.execute("""CREATE TABLE IF NOT EXISTS mood (
        date TEXT, sign TEXT, mood TEXT, n INTEGER DEFAULT 0,
        PRIMARY KEY (date, sign, mood))""")
    c.execute("""CREATE TABLE IF NOT EXISTS rating (
        sign TEXT, period TEXT, key TEXT, sum INTEGER DEFAULT 0, n INTEGER DEFAULT 0,
        PRIMARY KEY (sign, period, key))""")
    return c


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def vote_mood(sign: str, mood: str) -> dict:
    sign, mood = sign.lower().strip(), mood.lower().strip()
    if sign not in SIGNS or mood not in MOODS:
        raise ValueError("invalid sign or mood")
    with _lock, _conn() as c:
        c.execute("""INSERT INTO mood (date, sign, mood, n) VALUES (?,?,?,1)
                     ON CONFLICT(date, sign, mood) DO UPDATE SET n = n + 1""",
                  (_today(), sign, mood))
    return mood_results()


def mood_results(date: str | None = None) -> dict:
    date = date or _today()
    with _conn() as c:
        rows = c.execute("SELECT sign, mood, n FROM mood WHERE date=?", (date,)).fetchall()
    totals: dict = {m: 0 for m in MOODS}
    per_sign: dict = {}
    for sign, mood, n in rows:
        totals[mood] = totals.get(mood, 0) + n
        ps = per_sign.setdefault(sign, {})
        ps[mood] = ps.get(mood, 0) + n
    dominant = {s: max(ms, key=ms.get) for s, ms in per_sign.items()}
    return {"date": date, "totals": totals, "total": sum(totals.values()),
            "dominant_by_sign": dominant}


def add_rating(sign: str, period: str, key: str, stars: int) -> dict:
    sign, period = sign.lower().strip(), period.lower().strip()
    key = str(key)[:16]
    stars = int(stars)
    if sign not in SIGNS or period not in PERIODS or not 1 <= stars <= 5:
        raise ValueError("invalid rating")
    with _lock, _conn() as c:
        c.execute("""INSERT INTO rating (sign, period, key, sum, n) VALUES (?,?,?,?,1)
                     ON CONFLICT(sign, period, key) DO UPDATE
                     SET sum = sum + excluded.sum, n = n + 1""",
                  (sign, period, key, stars))
    return get_rating(sign, period, key)


def get_rating(sign: str, period: str, key: str) -> dict:
    with _conn() as c:
        row = c.execute("SELECT sum, n FROM rating WHERE sign=? AND period=? AND key=?",
                        (sign.lower(), period.lower(), str(key)[:16])).fetchone()
    s, n = row if row else (0, 0)
    return {"sign": sign, "period": period, "key": key,
            "average": round(s / n, 1) if n else None, "count": n}
