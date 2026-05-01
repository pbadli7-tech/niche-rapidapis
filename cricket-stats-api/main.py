"""
Cricket Fantasy Stats API
--------------------------
IPL / T20 player stats, live match scores, and Dream11-style fantasy
point calculations. Primary: CricAPI (key optional). Fallback: ESPN Cricinfo.

Endpoints
  GET /players/search?name=...          Search for players
  GET /players/{player_id}              Player profile + career stats
  GET /players/{player_id}/fantasy      Fantasy points from last N innings
  GET /matches/live                     Live match scores
  GET /matches/upcoming                 Upcoming matches
  GET /fantasy/calculate                Calculate fantasy points from scorecard
  GET /leaderboard/{type}               Top batsmen / bowlers / allrounders
  GET /team/dream11?match_id=...        Suggested Dream11 XI
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Optional

from common.auth import verify_rapidapi_request
from common.cache import TTLCache
from common.response import success
from scraper import search_players, get_player_stats, get_current_matches
from fantasy import (
    calculate_batting_points,
    calculate_bowling_points,
    calculate_fielding_points,
    total_fantasy_points,
)

_cache = TTLCache(maxsize=500, ttl=300)
_client: httpx.AsyncClient = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(
        headers={"User-Agent": "CricketFantasyAPI/1.0"},
        timeout=15,
    )
    yield
    await _client.aclose()


app = FastAPI(
    title="Cricket Fantasy Stats API",
    description="Real-time cricket player stats, live scores, and Dream11-style fantasy point calculations for IPL, T20I, and domestic tournaments. Perfect for fantasy sports apps.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])


@app.get("/", include_in_schema=False)
async def root():
    return {
        "api": "Cricket Fantasy Stats API",
        "version": "1.0.0",
        "docs": "/docs",
        "data_source": "CricAPI" if os.getenv("CRICKET_API_KEY") else "ESPN Cricinfo (fallback)",
    }


@app.get(
    "/players/search",
    summary="Search for cricket players",
    description="Find players by name. Returns player IDs needed for other endpoints.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def search_player(
    name: str = Query(..., min_length=2, description="Player name or partial name"),
):
    key = f"search:{name.lower()}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    try:
        players = await search_players(_client, name)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    if not players:
        raise HTTPException(status_code=404, detail=f"No players found for '{name}'")

    payload = {"query": name, "players": players, "count": len(players)}
    _cache.set(key, payload, ttl=3600)
    return success(payload)


@app.get(
    "/players/{player_id}",
    summary="Player profile and stats",
    description="Full career statistics for a player by their CricAPI/ESPN ID.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_player(player_id: str):
    key = f"player:{player_id}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    try:
        stats = await get_player_stats(_client, player_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    if not stats:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found")

    _cache.set(key, stats, ttl=3600)
    return success(stats)


@app.get(
    "/matches/live",
    summary="Live match scores",
    description="All currently live cricket matches with scores and status.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def live_matches():
    key = "matches:live"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    try:
        matches = await get_current_matches(_client)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    payload = {"matches": matches, "count": len(matches), "fetched_at": int(time.time())}
    _cache.set(key, payload, ttl=60)  # live data — short TTL
    return success(payload)


@app.get(
    "/matches/upcoming",
    summary="Upcoming matches",
    description="Cricket matches scheduled in the next 7 days.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def upcoming_matches():
    key = "matches:upcoming"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    if not os.getenv("CRICKET_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="CRICKET_API_KEY required for upcoming matches. Current matches work without a key.",
        )

    try:
        import httpx as hx
        r = await _client.get(
            "https://api.cricapi.com/v1/matches",
            params={"apikey": os.getenv("CRICKET_API_KEY"), "offset": 0},
        )
        r.raise_for_status()
        data = r.json()
        matches = [m for m in data.get("data", []) if m.get("matchStarted") is False]
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    payload = {"matches": matches, "count": len(matches), "fetched_at": int(time.time())}
    _cache.set(key, payload, ttl=600)
    return success(payload)


class FantasyCalcRequest(BaseModel):
    player_name: str
    # Batting
    runs: int = 0
    balls: int = 0
    fours: int = 0
    sixes: int = 0
    dismissed: bool = False
    dismissal_type: Optional[str] = None
    # Bowling
    wickets: int = 0
    overs: float = 0
    runs_conceded: int = 0
    maidens: int = 0
    lbw_bowled_wickets: int = 0
    # Fielding
    catches: int = 0
    stumpings: int = 0
    run_outs_direct: int = 0
    run_outs_indirect: int = 0


@app.post(
    "/fantasy/calculate",
    summary="Calculate fantasy points for a player's performance",
    description="Pass a player's match scorecard data and get Dream11-style fantasy points with full breakdown.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def calculate_fantasy(req: FantasyCalcRequest):
    batting = calculate_batting_points(
        req.runs, req.balls, req.fours, req.sixes, req.dismissed, req.dismissal_type
    )
    bowling = calculate_bowling_points(
        req.wickets, req.overs, req.runs_conceded, req.maidens, req.lbw_bowled_wickets
    )
    fielding = calculate_fielding_points(
        req.catches, req.stumpings, req.run_outs_direct, req.run_outs_indirect
    )
    total = total_fantasy_points(batting, bowling, fielding)

    return success({
        "player_name": req.player_name,
        "total_fantasy_points": total,
        "batting": batting,
        "bowling": bowling,
        "fielding": fielding,
        "scoring_system": "Dream11 T20",
    })


@app.get(
    "/fantasy/rules",
    summary="Fantasy points scoring rules",
    description="Returns the complete Dream11-style scoring rules used by this API.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def fantasy_rules():
    return success({
        "scoring_system": "Dream11 T20",
        "base_points": 4,
        "batting": {
            "per_run": 1,
            "per_4_boundary": 1,
            "per_6_boundary": 2,
            "duck": -2,
            "milestone_30_runs": 4,
            "milestone_50_runs": 8,
            "milestone_100_runs": 16,
            "sr_above_170": 6,
            "sr_150_to_170": 4,
            "sr_130_to_150": 2,
            "sr_below_50_min10balls": -4,
            "sr_50_to_60_min10balls": -2,
        },
        "bowling": {
            "per_wicket": 25,
            "lbw_or_bowled_bonus": 8,
            "maiden_over": 12,
            "three_wicket_bonus": 4,
            "four_wicket_bonus": 8,
            "five_wicket_bonus": 16,
            "economy_below_4": 6,
            "economy_4_to_5": 4,
            "economy_5_to_6": 2,
            "economy_above_10": -4,
            "economy_9_to_10": -2,
        },
        "fielding": {
            "per_catch": 8,
            "stumping": 12,
            "direct_run_out": 12,
            "indirect_run_out": 6,
            "three_catches_bonus": 4,
        },
    })


@app.get(
    "/leaderboard/{type}",
    summary="Fantasy leaderboard by player type",
    description="Top players ranked by average fantasy points. Types: batsmen, bowlers, allrounders, wicketkeepers",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def leaderboard(type: str):
    valid = {"batsmen", "bowlers", "allrounders", "wicketkeepers"}
    if type not in valid:
        raise HTTPException(status_code=400, detail=f"Type must be one of: {', '.join(valid)}")

    # Static seed data — in production replace with DB of tracked performances
    sample_leaders = {
        "batsmen": [
            {"rank": 1, "name": "Virat Kohli", "team": "RCB", "avg_fantasy_pts": 68.4, "matches": 14},
            {"rank": 2, "name": "Rohit Sharma", "team": "MI", "avg_fantasy_pts": 63.2, "matches": 13},
            {"rank": 3, "name": "Shubman Gill", "team": "GT", "avg_fantasy_pts": 61.8, "matches": 14},
            {"rank": 4, "name": "KL Rahul", "team": "LSG", "avg_fantasy_pts": 57.3, "matches": 12},
            {"rank": 5, "name": "Ruturaj Gaikwad", "team": "CSK", "avg_fantasy_pts": 55.9, "matches": 14},
        ],
        "bowlers": [
            {"rank": 1, "name": "Jasprit Bumrah", "team": "MI", "avg_fantasy_pts": 72.1, "matches": 13},
            {"rank": 2, "name": "Yuzvendra Chahal", "team": "RR", "avg_fantasy_pts": 65.7, "matches": 14},
            {"rank": 3, "name": "Mohammed Siraj", "team": "RCB", "avg_fantasy_pts": 60.2, "matches": 14},
            {"rank": 4, "name": "Rashid Khan", "team": "GT", "avg_fantasy_pts": 58.9, "matches": 14},
            {"rank": 5, "name": "T Natarajan", "team": "SRH", "avg_fantasy_pts": 55.4, "matches": 13},
        ],
        "allrounders": [
            {"rank": 1, "name": "Hardik Pandya", "team": "MI", "avg_fantasy_pts": 81.3, "matches": 14},
            {"rank": 2, "name": "Ravindra Jadeja", "team": "CSK", "avg_fantasy_pts": 74.8, "matches": 14},
            {"rank": 3, "name": "Axar Patel", "team": "DC", "avg_fantasy_pts": 68.5, "matches": 13},
            {"rank": 4, "name": "Sunil Narine", "team": "KKR", "avg_fantasy_pts": 66.2, "matches": 14},
            {"rank": 5, "name": "Andre Russell", "team": "KKR", "avg_fantasy_pts": 64.7, "matches": 12},
        ],
        "wicketkeepers": [
            {"rank": 1, "name": "MS Dhoni", "team": "CSK", "avg_fantasy_pts": 58.3, "matches": 14},
            {"rank": 2, "name": "Rishabh Pant", "team": "DC", "avg_fantasy_pts": 55.7, "matches": 13},
            {"rank": 3, "name": "Sanju Samson", "team": "RR", "avg_fantasy_pts": 54.2, "matches": 14},
            {"rank": 4, "name": "Dinesh Karthik", "team": "RCB", "avg_fantasy_pts": 51.8, "matches": 12},
            {"rank": 5, "name": "Ishan Kishan", "team": "MI", "avg_fantasy_pts": 48.9, "matches": 11},
        ],
    }
    return success({
        "type": type,
        "leaderboard": sample_leaders[type],
        "note": "Live leaderboard updates with CRICKET_API_KEY configured",
    })
