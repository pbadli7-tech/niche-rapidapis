"""
Cricket data fetcher.
Primary: CricAPI (free tier, 500 req/day) if CRICKET_API_KEY is set.
Fallback chain: ESPN Cricinfo → built-in static IPL/T20 roster.
"""
import os
import httpx
from typing import Optional

from players_db import search_static, get_static, PLAYERS

CRICKET_API_KEY = os.getenv("CRICKET_API_KEY", "")
CRICAPI_BASE = "https://api.cricapi.com/v1"
ESPN_MOBILE = "https://hs-consumer-api.espncricinfo.com/v1"


# ─── Public API ──────────────────────────────────────────────────────────────

async def search_players(client: httpx.AsyncClient, name: str) -> list:
    """Try CricAPI → ESPN → static roster."""
    # 1. CricAPI
    if CRICKET_API_KEY:
        results = await _cricapi_search_players(client, name)
        if results:
            return results
    # 2. ESPN Cricinfo
    results = await _espn_search_players(client, name)
    if results:
        return results
    # 3. Static fallback (always works)
    return search_static(name)


async def get_player_stats(client: httpx.AsyncClient, player_id: str) -> Optional[dict]:
    if CRICKET_API_KEY:
        stats = await _cricapi_player_stats(client, player_id)
        if stats:
            return stats
    espn = await _espn_player_stats(client, player_id)
    if espn:
        return espn
    # Static fallback
    static = get_static(player_id)
    if static:
        return {**static, "stats_note": "Profile from built-in roster. For live career stats, configure CRICKET_API_KEY."}
    return None


async def get_current_matches(client: httpx.AsyncClient) -> list:
    if CRICKET_API_KEY:
        results = await _cricapi_current_matches(client)
        if results:
            return results
    return await _espn_current_matches(client)


async def get_upcoming_matches(client: httpx.AsyncClient) -> list:
    """Always returns something — falls back to a static schedule preview if no API key."""
    if CRICKET_API_KEY:
        try:
            r = await client.get(
                f"{CRICAPI_BASE}/matches",
                params={"apikey": CRICKET_API_KEY, "offset": 0},
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            return [m for m in data if m.get("matchStarted") in (False, "false")][:20]
        except Exception:
            pass
    # Static placeholder (so endpoint never 503s)
    return [
        {
            "id": "static-1",
            "name": "Static Preview — configure CRICKET_API_KEY for live data",
            "team1": "—",
            "team2": "—",
            "venue": "TBD",
            "date": "TBD",
            "matchType": "T20",
            "note": "This is a placeholder. Set CRICKET_API_KEY to fetch real upcoming matches.",
        }
    ]


async def get_series_matches(client: httpx.AsyncClient, series_id: str) -> list:
    if CRICKET_API_KEY:
        return await _cricapi_series(client, series_id)
    return []


# ─── CricAPI implementations ──────────────────────────────────────────────────

async def _cricapi_search_players(client: httpx.AsyncClient, name: str) -> list:
    try:
        r = await client.get(
            f"{CRICAPI_BASE}/players",
            params={"apikey": CRICKET_API_KEY, "search": name, "offset": 0},
        )
        r.raise_for_status()
        data = r.json()
        return data.get("data", [])
    except Exception:
        return []


async def _cricapi_player_stats(client: httpx.AsyncClient, player_id: str) -> Optional[dict]:
    try:
        r = await client.get(
            f"{CRICAPI_BASE}/players_info",
            params={"apikey": CRICKET_API_KEY, "id": player_id},
        )
        r.raise_for_status()
        data = r.json()
        return data.get("data")
    except Exception:
        return None


async def _cricapi_current_matches(client: httpx.AsyncClient) -> list:
    try:
        r = await client.get(
            f"{CRICAPI_BASE}/currentMatches",
            params={"apikey": CRICKET_API_KEY, "offset": 0},
        )
        r.raise_for_status()
        data = r.json()
        return data.get("data", [])
    except Exception:
        return []


async def _cricapi_series(client: httpx.AsyncClient, series_id: str) -> list:
    try:
        r = await client.get(
            f"{CRICAPI_BASE}/series_info",
            params={"apikey": CRICKET_API_KEY, "id": series_id},
        )
        r.raise_for_status()
        data = r.json()
        return data.get("data", {}).get("matchList", [])
    except Exception:
        return []


# ─── ESPN Cricinfo fallback ────────────────────────────────────────────────────

async def _espn_search_players(client: httpx.AsyncClient, name: str) -> list:
    """ESPN's search endpoints are unreliable / blocked from cloud IPs.
    Kept for completeness but typically returns []."""
    try:
        r = await client.get(
            "https://search-hs.api.espnscrum.com/suggestion/search/cricinfo",
            params={"query": name, "type": "player", "size": 10},
        )
        if r.status_code == 200:
            data = r.json()
            return [
                {
                    "id": str(p.get("id", "")),
                    "name": p.get("displayName", ""),
                    "country": p.get("teamName", ""),
                    "role": p.get("description", ""),
                }
                for p in data.get("results", [])
            ]
    except Exception:
        pass
    return []


async def _espn_player_stats(client: httpx.AsyncClient, player_id: str) -> Optional[dict]:
    try:
        r = await client.get(
            f"{ESPN_MOBILE}/shared/player/career",
            params={"playerId": player_id, "type": "batting"},
        )
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


async def _espn_current_matches(client: httpx.AsyncClient) -> list:
    try:
        r = await client.get(
            f"{ESPN_MOBILE}/shared/match/list",
            params={"status": "live", "includedTypes": "INTERNATIONAL,DOMESTIC"},
        )
        if r.status_code != 200:
            return []
        data = r.json()
        matches = []
        for m in data.get("content", {}).get("matches", []):
            matches.append({
                "id": str(m.get("objectId", "")),
                "title": m.get("title", ""),
                "status": m.get("statusText", ""),
                "team1": m.get("teams", [{}])[0].get("team", {}).get("longName"),
                "team2": m.get("teams", [{}])[1].get("team", {}).get("longName") if len(m.get("teams", [])) > 1 else None,
                "series": m.get("series", {}).get("longName"),
                "venue": m.get("ground", {}).get("longName"),
            })
        return matches
    except Exception:
        return []
