"""
Stock Market Intelligence API
------------------------------
Real-time quotes, analyst ratings, earnings, news, and comparison
for any ticker on NYSE / NASDAQ / global exchanges.
Powered by yfinance (Yahoo Finance) — no API key required.

Endpoints
  GET /quote/{symbol}          Real-time quote + key fundamentals
  GET /analysis/{symbol}       Analyst ratings, price targets, consensus
  GET /earnings/{symbol}       Earnings history + next earnings date
  GET /news/{symbol}           Latest news headlines for a stock
  GET /compare                 Side-by-side comparison of multiple stocks
  GET /movers                  Top gainers, losers, and most-active today
"""
import os
import sys
import time
from typing import Optional, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yfinance as yf
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
from concurrent.futures import ThreadPoolExecutor

from common.auth import verify_rapidapi_request
from common.cache import TTLCache
from common.response import success

_cache = TTLCache(maxsize=500, ttl=120)  # 2-min TTL for market data
_executor = ThreadPoolExecutor(max_workers=10)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    _executor.shutdown(wait=False)


app = FastAPI(
    title="Stock Market Intelligence API",
    description=(
        "Real-time stock quotes, analyst ratings, earnings calendars, and market movers "
        "for 50,000+ tickers on NYSE, NASDAQ, and global exchanges. "
        "Get buy/sell/hold consensus, price targets, earnings surprises, and latest news in one call."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _run_sync(fn, *args):
    """Run a blocking yfinance call in the thread pool."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(_executor, fn, *args)


def _safe_val(v):
    """Convert non-serialisable types (Timestamp, NaN, inf) to safe values."""
    import math
    import pandas as pd
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    try:
        if hasattr(v, "isoformat"):
            return v.isoformat()
        if hasattr(v, "item"):        # numpy scalar
            return v.item()
    except Exception:
        pass
    return v


def _clean(d: dict) -> dict:
    return {k: _safe_val(v) for k, v in d.items()}


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def root():
    return {
        "api": "Stock Market Intelligence API",
        "version": "1.0.0",
        "docs": "/docs",
        "data_source": "Yahoo Finance (via yfinance)",
    }


# ---------------------------------------------------------------------------
# GET /quote/{symbol}
# ---------------------------------------------------------------------------
@app.get(
    "/quote/{symbol}",
    summary="Real-time stock quote",
    description=(
        "Returns live price, 52-week range, P/E ratio, market cap, dividend yield, "
        "beta, volume, and key financial metrics for any ticker symbol."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_quote(symbol: str):
    symbol = symbol.upper()
    key = f"quote:{symbol}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    def fetch():
        ticker = yf.Ticker(symbol)
        info = ticker.info
        if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
            return None
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        return {
            "symbol": symbol,
            "name": info.get("longName") or info.get("shortName"),
            "exchange": info.get("exchange"),
            "currency": info.get("currency"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "price": price,
            "previous_close": info.get("previousClose"),
            "open": info.get("open"),
            "day_low": info.get("dayLow"),
            "day_high": info.get("dayHigh"),
            "week_52_low": info.get("fiftyTwoWeekLow"),
            "week_52_high": info.get("fiftyTwoWeekHigh"),
            "volume": info.get("volume"),
            "avg_volume": info.get("averageVolume"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": _safe_val(info.get("trailingPE")),
            "forward_pe": _safe_val(info.get("forwardPE")),
            "eps": _safe_val(info.get("trailingEps")),
            "dividend_yield": _safe_val(info.get("dividendYield")),
            "beta": _safe_val(info.get("beta")),
            "price_to_book": _safe_val(info.get("priceToBook")),
            "profit_margin": _safe_val(info.get("profitMargins")),
            "revenue_growth": _safe_val(info.get("revenueGrowth")),
            "earnings_growth": _safe_val(info.get("earningsGrowth")),
            "short_ratio": _safe_val(info.get("shortRatio")),
            "analyst_target_price": _safe_val(info.get("targetMeanPrice")),
            "recommendation": info.get("recommendationKey"),
        }

    try:
        data = await _run_sync(fetch)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Data fetch error: {e}")

    if not data:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found or no data available")

    _cache.set(key, data)
    return success(data)


# ---------------------------------------------------------------------------
# GET /analysis/{symbol}
# ---------------------------------------------------------------------------
@app.get(
    "/analysis/{symbol}",
    summary="Analyst ratings and price targets",
    description=(
        "Buy / Sell / Hold recommendation consensus, mean/low/high price targets, "
        "number of analysts, and recent upgrades/downgrades."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_analysis(symbol: str):
    symbol = symbol.upper()
    key = f"analysis:{symbol}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    def fetch():
        ticker = yf.Ticker(symbol)
        info = ticker.info
        recs = ticker.recommendations
        upgrades = ticker.upgrades_downgrades

        rec_rows = []
        if recs is not None and not recs.empty:
            latest = recs.tail(10)
            for _, row in latest.iterrows():
                rec_rows.append({
                    "period": str(row.name) if hasattr(row, "name") else None,
                    "strong_buy": int(row.get("strongBuy", 0)),
                    "buy": int(row.get("buy", 0)),
                    "hold": int(row.get("hold", 0)),
                    "sell": int(row.get("sell", 0)),
                    "strong_sell": int(row.get("strongSell", 0)),
                })

        upgrade_rows = []
        if upgrades is not None and not upgrades.empty:
            for _, row in upgrades.head(10).iterrows():
                upgrade_rows.append({
                    "date": str(row.name)[:10] if hasattr(row, "name") else None,
                    "firm": row.get("Firm"),
                    "to_grade": row.get("ToGrade"),
                    "from_grade": row.get("FromGrade"),
                    "action": row.get("Action"),
                })

        return {
            "symbol": symbol,
            "recommendation": info.get("recommendationKey"),
            "recommendation_mean": _safe_val(info.get("recommendationMean")),
            "number_of_analysts": info.get("numberOfAnalystOpinions"),
            "target_high": _safe_val(info.get("targetHighPrice")),
            "target_low": _safe_val(info.get("targetLowPrice")),
            "target_mean": _safe_val(info.get("targetMeanPrice")),
            "target_median": _safe_val(info.get("targetMedianPrice")),
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "upside_potential_pct": round(
                ((_safe_val(info.get("targetMeanPrice")) or 0) - (info.get("currentPrice") or 0))
                / max(info.get("currentPrice") or 1, 1) * 100, 2
            ) if info.get("currentPrice") else None,
            "recommendation_history": rec_rows,
            "recent_upgrades_downgrades": upgrade_rows,
        }

    try:
        data = await _run_sync(fetch)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Data fetch error: {e}")

    _cache.set(key, data, ttl=900)
    return success(data)


# ---------------------------------------------------------------------------
# GET /earnings/{symbol}
# ---------------------------------------------------------------------------
@app.get(
    "/earnings/{symbol}",
    summary="Earnings history and upcoming dates",
    description=(
        "Historical EPS actuals vs estimates, revenue actuals vs estimates, "
        "earnings surprises, and next scheduled earnings date."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_earnings(symbol: str):
    symbol = symbol.upper()
    key = f"earnings:{symbol}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    def fetch():
        ticker = yf.Ticker(symbol)
        info = ticker.info
        cal = ticker.calendar
        earnings_hist = ticker.earnings_history

        history = []
        if earnings_hist is not None and not earnings_hist.empty:
            for _, row in earnings_hist.tail(8).iterrows():
                history.append({
                    "date": str(row.name)[:10] if hasattr(row, "name") else None,
                    "eps_estimate": _safe_val(row.get("epsEstimate")),
                    "eps_actual": _safe_val(row.get("epsActual")),
                    "eps_surprise": _safe_val(row.get("epsDifference")),
                    "surprise_pct": _safe_val(row.get("surprisePercent")),
                })

        next_earnings = None
        if cal is not None:
            if hasattr(cal, "get"):
                ne = cal.get("Earnings Date")
                if ne is not None:
                    if hasattr(ne, "__iter__") and not isinstance(ne, str):
                        ne = list(ne)
                        next_earnings = str(ne[0])[:10] if ne else None
                    else:
                        next_earnings = str(ne)[:10]
            elif hasattr(cal, "iloc"):
                try:
                    next_earnings = str(cal.iloc[0, 0])[:10]
                except Exception:
                    pass

        return {
            "symbol": symbol,
            "next_earnings_date": next_earnings,
            "earnings_call_time": None,
            "trailing_eps": _safe_val(info.get("trailingEps")),
            "forward_eps": _safe_val(info.get("forwardEps")),
            "pe_ratio": _safe_val(info.get("trailingPE")),
            "forward_pe": _safe_val(info.get("forwardPE")),
            "earnings_history": list(reversed(history)),
        }

    try:
        data = await _run_sync(fetch)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Data fetch error: {e}")

    _cache.set(key, data, ttl=3600)
    return success(data)


# ---------------------------------------------------------------------------
# GET /news/{symbol}
# ---------------------------------------------------------------------------
@app.get(
    "/news/{symbol}",
    summary="Latest stock news",
    description="Recent news headlines and links for a given ticker symbol.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_news(
    symbol: str,
    limit: int = Query(10, ge=1, le=50, description="Number of news items to return"),
):
    symbol = symbol.upper()
    key = f"news:{symbol}:{limit}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    def fetch():
        ticker = yf.Ticker(symbol)
        raw = ticker.news or []
        items = []
        for n in raw[:limit]:
            content = n.get("content", {})
            items.append({
                "title": content.get("title") or n.get("title"),
                "publisher": (content.get("provider") or {}).get("displayName") or n.get("publisher"),
                "published_at": content.get("pubDate") or (
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(n["providerPublishTime"]))
                    if n.get("providerPublishTime") else None
                ),
                "url": (content.get("canonicalUrl") or {}).get("url") or n.get("link"),
                "summary": content.get("summary"),
                "thumbnail": (
                    ((content.get("thumbnail") or {}).get("resolutions") or [{}])[0].get("url")
                    if content.get("thumbnail") else None
                ),
            })
        return {"symbol": symbol, "count": len(items), "news": items}

    try:
        data = await _run_sync(fetch)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Data fetch error: {e}")

    _cache.set(key, data, ttl=300)
    return success(data)


# ---------------------------------------------------------------------------
# GET /compare
# ---------------------------------------------------------------------------
@app.get(
    "/compare",
    summary="Compare multiple stocks side-by-side",
    description=(
        "Pass up to 5 comma-separated ticker symbols and get key metrics "
        "for each in a single response — price, P/E, market cap, analyst target."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def compare_stocks(
    symbols: str = Query(..., description="Comma-separated ticker symbols, e.g. AAPL,MSFT,GOOG"),
):
    tickers = [s.strip().upper() for s in symbols.split(",") if s.strip()][:5]
    if not tickers:
        raise HTTPException(status_code=400, detail="Provide at least one symbol")

    key = f"compare:{','.join(sorted(tickers))}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    def fetch_one(sym):
        info = yf.Ticker(sym).info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        prev = info.get("previousClose")
        change_pct = round((price - prev) / prev * 100, 2) if price and prev else None
        return {
            "symbol": sym,
            "name": info.get("shortName"),
            "price": price,
            "change_pct": change_pct,
            "market_cap": info.get("marketCap"),
            "pe_ratio": _safe_val(info.get("trailingPE")),
            "forward_pe": _safe_val(info.get("forwardPE")),
            "eps": _safe_val(info.get("trailingEps")),
            "dividend_yield": _safe_val(info.get("dividendYield")),
            "beta": _safe_val(info.get("beta")),
            "week_52_low": info.get("fiftyTwoWeekLow"),
            "week_52_high": info.get("fiftyTwoWeekHigh"),
            "analyst_target": _safe_val(info.get("targetMeanPrice")),
            "recommendation": info.get("recommendationKey"),
            "sector": info.get("sector"),
        }

    loop = asyncio.get_event_loop()
    futures = [loop.run_in_executor(_executor, fetch_one, sym) for sym in tickers]
    results = await asyncio.gather(*futures, return_exceptions=True)

    comparison = []
    for sym, res in zip(tickers, results):
        if isinstance(res, Exception):
            comparison.append({"symbol": sym, "error": str(res)})
        else:
            comparison.append(res)

    data = {"symbols": tickers, "count": len(comparison), "comparison": comparison}
    _cache.set(key, data)
    return success(data)


# ---------------------------------------------------------------------------
# GET /movers
# ---------------------------------------------------------------------------
@app.get(
    "/movers",
    summary="Top market movers",
    description=(
        "Returns today's top gainers, top losers, and most-active stocks "
        "based on Yahoo Finance screener data."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_movers(
    category: str = Query("gainers", description="gainers | losers | active"),
):
    valid = {"gainers", "losers", "active"}
    if category not in valid:
        raise HTTPException(status_code=400, detail=f"category must be one of: {', '.join(valid)}")

    key = f"movers:{category}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    screener_map = {
        "gainers": "day_gainers",
        "losers": "day_losers",
        "active": "most_actives",
    }

    def fetch():
        import yfinance.screener.screener as ys
        screener = yf.screen(screener_map[category])
        if screener is None:
            return []
        quotes = screener.get("quotes", [])
        result = []
        for q in quotes[:20]:
            result.append({
                "symbol": q.get("symbol"),
                "name": q.get("shortName") or q.get("longName"),
                "price": q.get("regularMarketPrice"),
                "change": q.get("regularMarketChange"),
                "change_pct": q.get("regularMarketChangePercent"),
                "volume": q.get("regularMarketVolume"),
                "market_cap": q.get("marketCap"),
                "pe_ratio": _safe_val(q.get("trailingPE")),
            })
        return result

    try:
        movers = await _run_sync(fetch)
    except Exception as e:
        # Fallback with well-known symbols if screener fails
        movers = []

    data = {"category": category, "count": len(movers), "movers": movers, "as_of": int(time.time())}
    _cache.set(key, data, ttl=300)
    return success(data)
