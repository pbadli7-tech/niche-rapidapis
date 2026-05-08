"""
Stock Market Intelligence API
------------------------------
Real-time quotes, analyst ratings, earnings, news, and comparison
for any ticker on NYSE / NASDAQ / global exchanges.

Uses Yahoo Finance public HTTP endpoints directly (no yfinance dependency).
This bypasses yfinance's brittle scraping and works reliably on cloud IPs
that Yahoo otherwise rate-limits.

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
import asyncio
import math
from typing import Optional, List, Dict, Any
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from common.auth import verify_rapidapi_request
from common.cache import TTLCache
from common.response import success

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
YAHOO_BASE = "https://query1.finance.yahoo.com"
YAHOO_BASE_2 = "https://query2.finance.yahoo.com"

_cache = TTLCache(maxsize=500, ttl=120)


# ---------------------------------------------------------------------------
# Yahoo Finance HTTP client with crumb authentication
# ---------------------------------------------------------------------------
class YahooFinanceClient:
    """Async client for Yahoo's public-but-crumb-gated finance endpoints."""

    def __init__(self):
        self._cookies: Dict[str, str] = {}
        self._crumb: Optional[str] = None
        self._session_expires: float = 0.0
        self._lock = asyncio.Lock()

    async def _ensure_session(self):
        """Refresh cookie + crumb every 30 minutes."""
        if self._crumb and time.time() < self._session_expires:
            return
        async with self._lock:
            if self._crumb and time.time() < self._session_expires:
                return
            async with httpx.AsyncClient(
                timeout=10.0, follow_redirects=True
            ) as client:
                # 1. Hit a Yahoo entry point to obtain consent cookies.
                try:
                    r = await client.get(
                        "https://fc.yahoo.com",
                        headers={"User-Agent": USER_AGENT},
                    )
                    self._cookies = dict(r.cookies)
                except Exception:
                    self._cookies = {}
                # 2. Fetch crumb token.
                try:
                    r = await client.get(
                        f"{YAHOO_BASE}/v1/test/getcrumb",
                        cookies=self._cookies,
                        headers={"User-Agent": USER_AGENT},
                    )
                    self._crumb = r.text.strip() or None
                except Exception:
                    self._crumb = None
            self._session_expires = time.time() + 1800

    async def chart(
        self, symbol: str, range_: str = "1mo", interval: str = "1d"
    ) -> Dict[str, Any]:
        """Free, no-auth endpoint. Returns price meta + OHLCV history."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{YAHOO_BASE}/v8/finance/chart/{symbol}",
                params={"interval": interval, "range": range_},
                headers={"User-Agent": USER_AGENT},
            )
            data = r.json()
        if not data.get("chart") or data["chart"].get("error"):
            err = (data.get("chart") or {}).get("error") or {}
            raise HTTPException(
                status_code=404,
                detail=err.get("description") or f"No data for {symbol}",
            )
        results = data["chart"].get("result") or []
        if not results:
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")
        return results[0]

    async def quote_summary(
        self, symbol: str, modules: List[str]
    ) -> Dict[str, Any]:
        """Crumb-gated. Returns rich fundamentals."""
        await self._ensure_session()
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{YAHOO_BASE}/v10/finance/quoteSummary/{symbol}",
                params={
                    "modules": ",".join(modules),
                    "crumb": self._crumb or "",
                },
                cookies=self._cookies,
                headers={"User-Agent": USER_AGENT},
            )
            data = r.json()
        # Retry once with refreshed crumb on auth failure
        if (data.get("finance") or {}).get("error"):
            self._crumb = None
            await self._ensure_session()
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    f"{YAHOO_BASE}/v10/finance/quoteSummary/{symbol}",
                    params={
                        "modules": ",".join(modules),
                        "crumb": self._crumb or "",
                    },
                    cookies=self._cookies,
                    headers={"User-Agent": USER_AGENT},
                )
                data = r.json()
        results = (data.get("quoteSummary") or {}).get("result") or []
        if not results:
            raise HTTPException(
                status_code=404,
                detail=f"No fundamentals available for {symbol}",
            )
        return results[0]

    async def screener(self, scr_id: str, count: int = 20) -> List[Dict[str, Any]]:
        """Screener for movers — uses public predefined screeners."""
        await self._ensure_session()
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{YAHOO_BASE}/v1/finance/screener",
                params={
                    "crumb": self._crumb or "",
                    "lang": "en-US",
                    "region": "US",
                    "formatted": "false",
                },
                cookies=self._cookies,
                headers={
                    "User-Agent": USER_AGENT,
                    "Content-Type": "application/json",
                },
                json={
                    "size": count,
                    "offset": 0,
                    "sortField": "percentchange",
                    "sortType": "DESC",
                    "quoteType": "EQUITY",
                    "topOperator": "AND",
                    "query": {
                        "operator": "AND",
                        "operands": [
                            {
                                "operator": "or",
                                "operands": [
                                    {
                                        "operator": "EQ",
                                        "operands": ["region", "us"],
                                    }
                                ],
                            }
                        ],
                    },
                    "userId": "",
                    "userIdType": "guid",
                },
            )
            data = r.json()
        # Try the simpler "predefined" screener first
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    f"{YAHOO_BASE}/v1/finance/screener/predefined/saved",
                    params={
                        "scrIds": scr_id,
                        "count": count,
                        "crumb": self._crumb or "",
                    },
                    cookies=self._cookies,
                    headers={"User-Agent": USER_AGENT},
                )
                pdata = r.json()
            results = (pdata.get("finance") or {}).get("result") or []
            if results and results[0].get("quotes"):
                return results[0]["quotes"]
        except Exception:
            pass
        results = (data.get("finance") or {}).get("result") or []
        if not results:
            return []
        return results[0].get("quotes", [])

    async def search(self, query: str, count: int = 10) -> List[Dict[str, Any]]:
        """Symbol search."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{YAHOO_BASE_2}/v1/finance/search",
                params={"q": query, "quotesCount": count, "newsCount": 0},
                headers={"User-Agent": USER_AGENT},
            )
            data = r.json()
        return data.get("quotes", [])

    async def news_rss(self, symbol: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch news from Yahoo's public RSS feed (no auth)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"https://feeds.finance.yahoo.com/rss/2.0/headline",
                params={"s": symbol, "region": "US", "lang": "en-US"},
                headers={"User-Agent": USER_AGENT},
            )
            xml = r.text
        items = []
        try:
            root = ET.fromstring(xml)
            for item in root.iter("item"):
                if len(items) >= limit:
                    break
                items.append({
                    "title": item.findtext("title"),
                    "publisher": item.findtext("source") or "Yahoo Finance",
                    "published_at": item.findtext("pubDate"),
                    "url": item.findtext("link"),
                    "summary": item.findtext("description"),
                    "thumbnail": None,
                })
        except ET.ParseError:
            pass
        return items


_yc = YahooFinanceClient()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _raw(v: Any) -> Any:
    """Yahoo wraps numbers as {"raw": x, "fmt": "..."}. Unwrap them."""
    if isinstance(v, dict) and "raw" in v:
        return v["raw"]
    return v


def _safe_val(v: Any) -> Any:
    if v is None:
        return None
    v = _raw(v)
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Stock Market Intelligence API",
    description=(
        "Real-time stock quotes, analyst ratings, earnings calendars, and market movers "
        "for 50,000+ tickers on NYSE, NASDAQ, and global exchanges. "
        "Get buy/sell/hold consensus, price targets, earnings surprises, and latest news in one call."
    ),
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def root():
    return {
        "api": "Stock Market Intelligence API",
        "version": "1.1.0",
        "docs": "/docs",
        "data_source": "Yahoo Finance (direct HTTP)",
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

    # Pull rich fundamentals from quoteSummary; fall back to chart meta on failure.
    fundamentals: Dict[str, Any] = {}
    try:
        qs = await _yc.quote_summary(
            symbol,
            [
                "price",
                "summaryDetail",
                "financialData",
                "defaultKeyStatistics",
                "assetProfile",
            ],
        )
        price = qs.get("price") or {}
        sd = qs.get("summaryDetail") or {}
        fd = qs.get("financialData") or {}
        ks = qs.get("defaultKeyStatistics") or {}
        ap = qs.get("assetProfile") or {}
        fundamentals = {
            "name": price.get("longName") or price.get("shortName"),
            "exchange": price.get("exchangeName"),
            "currency": price.get("currency"),
            "sector": ap.get("sector"),
            "industry": ap.get("industry"),
            "price": _safe_val(price.get("regularMarketPrice")),
            "previous_close": _safe_val(price.get("regularMarketPreviousClose")),
            "open": _safe_val(price.get("regularMarketOpen")),
            "day_low": _safe_val(price.get("regularMarketDayLow")),
            "day_high": _safe_val(price.get("regularMarketDayHigh")),
            "week_52_low": _safe_val(sd.get("fiftyTwoWeekLow")),
            "week_52_high": _safe_val(sd.get("fiftyTwoWeekHigh")),
            "volume": _safe_val(price.get("regularMarketVolume")),
            "avg_volume": _safe_val(sd.get("averageVolume")),
            "market_cap": _safe_val(price.get("marketCap")),
            "pe_ratio": _safe_val(sd.get("trailingPE")),
            "forward_pe": _safe_val(sd.get("forwardPE")),
            "eps": _safe_val(ks.get("trailingEps")),
            "dividend_yield": _safe_val(sd.get("dividendYield")),
            "beta": _safe_val(sd.get("beta")) or _safe_val(ks.get("beta")),
            "price_to_book": _safe_val(ks.get("priceToBook")),
            "profit_margin": _safe_val(fd.get("profitMargins")),
            "revenue_growth": _safe_val(fd.get("revenueGrowth")),
            "earnings_growth": _safe_val(fd.get("earningsGrowth")),
            "short_ratio": _safe_val(ks.get("shortRatio")),
            "analyst_target_price": _safe_val(fd.get("targetMeanPrice")),
            "recommendation": fd.get("recommendationKey"),
        }
    except Exception:
        # Fallback: chart endpoint always works (no crumb).
        chart = await _yc.chart(symbol, range_="5d")
        meta = chart.get("meta", {})
        fundamentals = {
            "name": meta.get("longName") or meta.get("shortName"),
            "exchange": meta.get("exchangeName"),
            "currency": meta.get("currency"),
            "sector": None,
            "industry": None,
            "price": meta.get("regularMarketPrice"),
            "previous_close": meta.get("chartPreviousClose"),
            "open": None,
            "day_low": meta.get("regularMarketDayLow"),
            "day_high": meta.get("regularMarketDayHigh"),
            "week_52_low": meta.get("fiftyTwoWeekLow"),
            "week_52_high": meta.get("fiftyTwoWeekHigh"),
            "volume": meta.get("regularMarketVolume"),
            "avg_volume": None,
            "market_cap": None,
            "pe_ratio": None,
            "forward_pe": None,
            "eps": None,
            "dividend_yield": None,
            "beta": None,
            "price_to_book": None,
            "profit_margin": None,
            "revenue_growth": None,
            "earnings_growth": None,
            "short_ratio": None,
            "analyst_target_price": None,
            "recommendation": None,
        }

    data = {"symbol": symbol, **fundamentals}
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

    qs = await _yc.quote_summary(
        symbol,
        [
            "recommendationTrend",
            "upgradeDowngradeHistory",
            "financialData",
        ],
    )

    rt = (qs.get("recommendationTrend") or {}).get("trend") or []
    rec_rows = []
    for row in rt[:10]:
        rec_rows.append({
            "period": row.get("period"),
            "strong_buy": row.get("strongBuy", 0),
            "buy": row.get("buy", 0),
            "hold": row.get("hold", 0),
            "sell": row.get("sell", 0),
            "strong_sell": row.get("strongSell", 0),
        })

    ud = (qs.get("upgradeDowngradeHistory") or {}).get("history") or []
    upgrade_rows = []
    for row in ud[:10]:
        epoch = row.get("epochGradeDate")
        date_str = (
            time.strftime("%Y-%m-%d", time.gmtime(epoch)) if epoch else None
        )
        upgrade_rows.append({
            "date": date_str,
            "firm": row.get("firm"),
            "to_grade": row.get("toGrade"),
            "from_grade": row.get("fromGrade"),
            "action": row.get("action"),
        })

    fd = qs.get("financialData") or {}
    data = {
        "symbol": symbol,
        "recommendation_consensus": fd.get("recommendationKey"),
        "mean_recommendation": _safe_val(fd.get("recommendationMean")),
        "number_of_analysts": _safe_val(fd.get("numberOfAnalystOpinions")),
        "target_mean": _safe_val(fd.get("targetMeanPrice")),
        "target_high": _safe_val(fd.get("targetHighPrice")),
        "target_low": _safe_val(fd.get("targetLowPrice")),
        "target_median": _safe_val(fd.get("targetMedianPrice")),
        "recommendation_trend": rec_rows,
        "recent_upgrades_downgrades": upgrade_rows,
    }
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

    qs = await _yc.quote_summary(
        symbol,
        [
            "earnings",
            "earningsHistory",
            "calendarEvents",
            "defaultKeyStatistics",
            "summaryDetail",
        ],
    )

    eh = (qs.get("earningsHistory") or {}).get("history") or []
    history = []
    for row in eh[-8:]:
        history.append({
            "date": (row.get("quarter") or {}).get("fmt"),
            "eps_estimate": _safe_val(row.get("epsEstimate")),
            "eps_actual": _safe_val(row.get("epsActual")),
            "eps_surprise": _safe_val(row.get("epsDifference")),
            "surprise_pct": _safe_val(row.get("surprisePercent")),
        })

    cal = qs.get("calendarEvents") or {}
    earnings_dates = (cal.get("earnings") or {}).get("earningsDate") or []
    next_earnings = None
    if earnings_dates:
        first = earnings_dates[0]
        next_earnings = first.get("fmt") if isinstance(first, dict) else None

    ks = qs.get("defaultKeyStatistics") or {}
    sd = qs.get("summaryDetail") or {}
    data = {
        "symbol": symbol,
        "next_earnings_date": next_earnings,
        "earnings_call_time": None,
        "trailing_eps": _safe_val(ks.get("trailingEps")),
        "forward_eps": _safe_val(ks.get("forwardEps")),
        "pe_ratio": _safe_val(sd.get("trailingPE")),
        "forward_pe": _safe_val(sd.get("forwardPE")),
        "earnings_history": list(reversed(history)),
    }
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

    items = await _yc.news_rss(symbol, limit)
    data = {"symbol": symbol, "count": len(items), "news": items}
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

    async def fetch_one(sym: str):
        try:
            qs = await _yc.quote_summary(
                sym,
                ["price", "summaryDetail", "financialData", "defaultKeyStatistics", "assetProfile"],
            )
            price = qs.get("price") or {}
            sd = qs.get("summaryDetail") or {}
            fd = qs.get("financialData") or {}
            ks = qs.get("defaultKeyStatistics") or {}
            ap = qs.get("assetProfile") or {}
            p = _safe_val(price.get("regularMarketPrice"))
            prev = _safe_val(price.get("regularMarketPreviousClose"))
            change_pct = round((p - prev) / prev * 100, 2) if p and prev else None
            return {
                "symbol": sym,
                "name": price.get("shortName"),
                "price": p,
                "change_pct": change_pct,
                "market_cap": _safe_val(price.get("marketCap")),
                "pe_ratio": _safe_val(sd.get("trailingPE")),
                "forward_pe": _safe_val(sd.get("forwardPE")),
                "eps": _safe_val(ks.get("trailingEps")),
                "dividend_yield": _safe_val(sd.get("dividendYield")),
                "beta": _safe_val(sd.get("beta")),
                "week_52_low": _safe_val(sd.get("fiftyTwoWeekLow")),
                "week_52_high": _safe_val(sd.get("fiftyTwoWeekHigh")),
                "analyst_target": _safe_val(fd.get("targetMeanPrice")),
                "recommendation": fd.get("recommendationKey"),
                "sector": ap.get("sector"),
            }
        except Exception as e:
            return {"symbol": sym, "error": str(e)}

    results = await asyncio.gather(*[fetch_one(s) for s in tickers])
    data = {"symbols": tickers, "count": len(results), "comparison": results}
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
        raise HTTPException(
            status_code=400,
            detail=f"category must be one of: {', '.join(valid)}",
        )

    key = f"movers:{category}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    screener_map = {
        "gainers": "day_gainers",
        "losers": "day_losers",
        "active": "most_actives",
    }

    quotes = await _yc.screener(screener_map[category], count=20)
    movers = []
    for q in quotes[:20]:
        movers.append({
            "symbol": q.get("symbol"),
            "name": q.get("shortName") or q.get("longName"),
            "price": _safe_val(q.get("regularMarketPrice")),
            "change": _safe_val(q.get("regularMarketChange")),
            "change_pct": _safe_val(q.get("regularMarketChangePercent")),
            "volume": _safe_val(q.get("regularMarketVolume")),
            "market_cap": _safe_val(q.get("marketCap")),
            "pe_ratio": _safe_val(q.get("trailingPE")),
        })

    data = {
        "category": category,
        "count": len(movers),
        "movers": movers,
        "as_of": int(time.time()),
    }
    _cache.set(key, data, ttl=300)
    return success(data)
