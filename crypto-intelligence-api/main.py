"""
Crypto Intelligence API
-----------------------
Technical analysis + buy/sell signals for any CoinGecko-listed coin.
No API key required — powered by CoinGecko free tier.
"""
import os
import sys
import time
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import List, Optional

from common.auth import verify_rapidapi_request
from common.cache import TTLCache, cached
from common.response import success, error as err_resp
from signals import generate_signal

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")  # optional Pro key

_cache = TTLCache(maxsize=500, ttl=300)  # 5-min default TTL
_client: httpx.AsyncClient = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    headers = {"Accept": "application/json"}
    if COINGECKO_API_KEY:
        headers["x-cg-pro-api-key"] = COINGECKO_API_KEY
    _client = httpx.AsyncClient(headers=headers, timeout=15)
    yield
    await _client.aclose()


app = FastAPI(
    title="Crypto Intelligence API",
    description="Real-time technical analysis and trading signals for 10,000+ cryptocurrencies. RSI, MACD, Bollinger Bands, Moving Averages — all in one call.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


async def _cg_get(path: str, params: dict = None) -> dict:
    url = f"{COINGECKO_BASE}{path}"
    r = await _client.get(url, params=params)
    if r.status_code == 429:
        raise HTTPException(status_code=429, detail="Rate limit hit upstream — try again in 60s")
    r.raise_for_status()
    return r.json()


async def _fetch_ohlc(coin_id: str, days: int = 30) -> tuple[list, list]:
    """Return (prices, volumes) as flat float lists."""
    key = f"ohlc:{coin_id}:{days}"
    cached_val = _cache.get(key)
    if cached_val:
        return cached_val
    data = await _cg_get(f"/coins/{coin_id}/market_chart", params={"vs_currency": "usd", "days": days, "interval": "daily"})
    prices = [p[1] for p in data.get("prices", [])]
    volumes = [v[1] for v in data.get("total_volumes", [])]
    _cache.set(key, (prices, volumes), ttl=300)
    return prices, volumes


async def _fetch_coin_detail(coin_id: str) -> dict:
    key = f"detail:{coin_id}"
    cached_val = _cache.get(key)
    if cached_val:
        return cached_val
    data = await _cg_get(
        f"/coins/{coin_id}",
        params={"localization": "false", "tickers": "false", "community_data": "false", "developer_data": "false"},
    )
    _cache.set(key, data, ttl=180)
    return data


async def _resolve_coin_id(symbol: str) -> str:
    """Map ticker symbol like BTC → bitcoin."""
    symbol = symbol.lower()
    key = f"coinlist:symbol:{symbol}"
    cached_val = _cache.get(key)
    if cached_val:
        return cached_val
    coins = await _cg_get("/coins/list")
    match = next((c for c in coins if c["symbol"].lower() == symbol), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Coin symbol '{symbol.upper()}' not found")
    _cache.set(key, match["id"], ttl=3600)
    return match["id"]


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    return {"api": "Crypto Intelligence API", "version": "1.0.0", "docs": "/docs"}


@app.get(
    "/signal/{symbol}",
    summary="Get trading signal for a coin",
    description="Returns a BUY / SELL / HOLD signal with confidence score and supporting indicator values.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_signal(symbol: str):
    try:
        coin_id = await _resolve_coin_id(symbol)
        detail = await _fetch_coin_detail(coin_id)
        prices, volumes = await _fetch_ohlc(coin_id, days=60)

        md = detail.get("market_data", {})
        price_change_24h = md.get("price_change_percentage_24h") or 0
        price_change_7d = md.get("price_change_percentage_7d") or 0
        current_price = md.get("current_price", {}).get("usd") or (prices[-1] if prices else 0)

        analysis = generate_signal(prices, volumes, price_change_24h, price_change_7d)

        return success({
            "symbol": symbol.upper(),
            "name": detail.get("name"),
            "signal": analysis["signal"],
            "strength": analysis["strength"],
            "confidence": analysis["confidence"],
            "price_usd": current_price,
            "price_change_24h": price_change_24h,
            "reasoning": analysis["reasoning"],
            "indicators": analysis["indicators"],
            "generated_at": int(time.time()),
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/analysis/{symbol}",
    summary="Full technical analysis for a coin",
    description="Complete analysis including price history, market cap, all technical indicators, and signal.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_analysis(symbol: str):
    try:
        coin_id = await _resolve_coin_id(symbol)
        detail = await _fetch_coin_detail(coin_id)
        prices, volumes = await _fetch_ohlc(coin_id, days=60)

        md = detail.get("market_data", {})
        price_change_24h = md.get("price_change_percentage_24h") or 0
        price_change_7d = md.get("price_change_percentage_7d") or 0
        current_price = md.get("current_price", {}).get("usd") or (prices[-1] if prices else 0)

        # 7-day history for sparkline
        hist_data = await _cg_get(
            f"/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": 7, "interval": "daily"},
        )
        history_7d = [
            {"timestamp": int(p[0] / 1000), "price": p[1], "volume": v[1]}
            for p, v in zip(hist_data.get("prices", []), hist_data.get("total_volumes", []))
        ]

        analysis = generate_signal(prices, volumes, price_change_24h, price_change_7d)

        return success({
            "symbol": symbol.upper(),
            "name": detail.get("name"),
            "description": (detail.get("description", {}).get("en") or "")[:300],
            "price_usd": current_price,
            "market_cap": md.get("market_cap", {}).get("usd"),
            "volume_24h": md.get("total_volume", {}).get("usd"),
            "price_change_24h": price_change_24h,
            "price_change_7d": price_change_7d,
            "ath": md.get("ath", {}).get("usd"),
            "ath_change_percent": md.get("ath_change_percentage", {}).get("usd"),
            "indicators": analysis["indicators"],
            "signal": {
                "value": analysis["signal"],
                "strength": analysis["strength"],
                "confidence": analysis["confidence"],
                "reasoning": analysis["reasoning"],
            },
            "history_7d": history_7d,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/trending",
    summary="Trending coins with signals",
    description="Top 7 trending coins on CoinGecko with their current signals.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_trending():
    try:
        cached_val = _cache.get("trending")
        if cached_val:
            return success(cached_val)

        trending = await _cg_get("/search/trending")
        coins = trending.get("coins", [])[:7]

        results = []
        for item in coins:
            c = item.get("item", {})
            symbol = c.get("symbol", "").lower()
            coin_id = c.get("id")
            try:
                prices, volumes = await _fetch_ohlc(coin_id, days=30)
                analysis = generate_signal(prices, volumes, 0, 0)
                results.append({
                    "rank": c.get("market_cap_rank"),
                    "name": c.get("name"),
                    "symbol": symbol.upper(),
                    "coin_id": coin_id,
                    "signal": analysis["signal"],
                    "confidence": analysis["confidence"],
                    "thumb": c.get("thumb"),
                })
            except Exception:
                continue

        _cache.set("trending", results, ttl=600)
        return success(results)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/compare",
    summary="Compare signals for multiple coins",
    description="Pass up to 5 coin symbols and get a side-by-side signal comparison.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def compare_coins(symbols: str = Query(..., description="Comma-separated symbols, e.g. BTC,ETH,SOL")):
    syms = [s.strip().upper() for s in symbols.split(",")][:5]
    if not syms:
        raise HTTPException(status_code=400, detail="Provide at least one symbol")

    results = []
    for sym in syms:
        try:
            coin_id = await _resolve_coin_id(sym)
            detail = await _fetch_coin_detail(coin_id)
            prices, volumes = await _fetch_ohlc(coin_id, days=60)
            md = detail.get("market_data", {})
            price_change_24h = md.get("price_change_percentage_24h") or 0
            price_change_7d = md.get("price_change_percentage_7d") or 0
            current_price = md.get("current_price", {}).get("usd") or (prices[-1] if prices else 0)
            analysis = generate_signal(prices, volumes, price_change_24h, price_change_7d)
            results.append({
                "symbol": sym,
                "name": detail.get("name"),
                "price_usd": current_price,
                "price_change_24h": price_change_24h,
                "signal": analysis["signal"],
                "strength": analysis["strength"],
                "confidence": analysis["confidence"],
                "rsi_14": analysis["indicators"]["rsi_14"],
                "macd": analysis["indicators"]["macd"],
            })
        except HTTPException as e:
            results.append({"symbol": sym, "error": e.detail})

    return success(results)


@app.get(
    "/history/{symbol}",
    summary="Price history with volume",
    description="Historical OHLC data for any coin. Default 30 days.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_history(
    symbol: str,
    days: int = Query(30, ge=1, le=365, description="Number of days"),
):
    try:
        coin_id = await _resolve_coin_id(symbol)
        data = await _cg_get(
            f"/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": days, "interval": "daily"},
        )
        history = [
            {"timestamp": int(p[0] / 1000), "price": p[1], "volume": v[1]}
            for p, v in zip(data.get("prices", []), data.get("total_volumes", []))
        ]
        return success({"symbol": symbol.upper(), "days": days, "history": history})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
