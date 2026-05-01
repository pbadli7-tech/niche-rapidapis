"""
Cricket data fetcher.
Primary: CricAPI (free tier, 500 req/day) if CRICKET_API_KEY is set.
Fallback: ESPN Cricinfo scraping via their unofficial mobile API.
"""
import os
import re
import httpx
from typing import Optional

CRICKET_API_KEY = os.getenv("CRICKET_API_KEY", "")
CRICAPI_BASE = "https://api.cricapi.com/v1"

ESPN_MOBILE = "https://hs-consumer-api.espncricinfo.com/v1"


async def search_players(client: httpx.AsyncClient, name: str) -> list:
    if CRICKET_API_KEY:
        return await _cricapi_search_players(client, name)
    return await _espn_search_players(client, name)


async def get_player_stats(client: httpx.AsyncClient, player_id: str) -> Optional[dict]:
    if CRICKET_API_KEY:
        return await _cricapi_player_stats(client, player_id)
    return await _espn_player_stats(client, player_id)


async def get_current_matches(client: httpx.AsyncClient) -> list:
    if CRICKET_API_KEY:
        return await _cricapi_current_matches(client)
    return await _espn_current_matches(client)


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
    """Uses ESPN Cricinfo's search API (unofficial but public)."""
    try:
        r = await client.get(
            "https://www.espncricinfo.com/ci/content/player/search.html",
            params={"search": name},
            headers={"Accept": "application/json"},
        )
        # ESPN returns HTML — parse basic info
        # Use their API endpoint instead
        r2 = await client.get(
            f"https://search-hs.api.espnscrum.com/suggestion/search/cricinfo",
            params={"query": name, "type": "player", "size": 10},
        )
        if r2.status_code == 200:
            data = r2.json()
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
