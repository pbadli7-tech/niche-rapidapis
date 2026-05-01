"""
News Sentiment API
------------------
Real-time sentiment analysis on news headlines for any topic, company,
or keyword. Uses HuggingFace RoBERTa model with keyword fallback.

Endpoints
  GET /sentiment/{topic}       Aggregate sentiment for a topic
  GET /headlines/{country}     Top headlines with per-article sentiment
  GET /trending                Trending topics with sentiment scores
  POST /analyze                Analyze any custom text
  GET /compare?topics=...      Compare sentiment across topics
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
from typing import Optional, List

from common.auth import verify_rapidapi_request
from common.cache import TTLCache
from common.response import success
from analyzer import hf_sentiment, keyword_sentiment, aggregate_sentiments

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
NEWS_API_BASE = "https://newsapi.org/v2"

# GDELT free fallback (no key needed)
GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"

_cache = TTLCache(maxsize=500, ttl=900)
_client: httpx.AsyncClient = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(timeout=15)
    yield
    await _client.aclose()


app = FastAPI(
    title="News Sentiment API",
    description="Real-time sentiment analysis on news for any topic, stock ticker, company, or keyword. Returns positive/negative/neutral scores with a sentiment index (-100 to +100).",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])


async def _fetch_newsapi(query: str, page_size: int = 10, language: str = "en") -> list:
    if not NEWS_API_KEY:
        return []
    try:
        r = await _client.get(
            f"{NEWS_API_BASE}/everything",
            params={
                "q": query,
                "pageSize": page_size,
                "language": language,
                "sortBy": "publishedAt",
                "apiKey": NEWS_API_KEY,
            },
        )
        if r.status_code != 200:
            return []
        data = r.json()
        return data.get("articles", [])
    except Exception:
        return []


async def _fetch_gdelt(query: str, max_records: int = 10) -> list:
    """GDELT free API — no key needed, returns news articles."""
    try:
        r = await _client.get(
            GDELT_BASE,
            params={
                "query": query,
                "mode": "artlist",
                "maxrecords": max_records,
                "format": "json",
                "timespan": "24h",
            },
        )
        if r.status_code != 200:
            return []
        data = r.json()
        articles = data.get("articles", [])
        return [
            {
                "title": a.get("title", ""),
                "description": a.get("seendate", ""),
                "source": {"name": a.get("domain", "")},
                "url": a.get("url", ""),
                "publishedAt": a.get("seendate", ""),
            }
            for a in articles
        ]
    except Exception:
        return []


async def _articles_with_sentiment(query: str, max_articles: int = 15) -> tuple[list, list]:
    """Returns (articles_with_sentiment, raw_articles)."""
    articles = await _fetch_newsapi(query, page_size=max_articles)
    if not articles:
        articles = await _fetch_gdelt(query, max_records=max_articles)

    results = []
    sentiments = []
    for a in articles[:max_articles]:
        text = f"{a.get('title', '')} {a.get('description', '')}".strip()
        if not text:
            continue
        sentiment = await hf_sentiment(_client, text)
        sentiments.append(sentiment)
        results.append({
            "title": a.get("title"),
            "source": a.get("source", {}).get("name"),
            "url": a.get("url"),
            "published_at": a.get("publishedAt"),
            "sentiment": sentiment,
        })

    return results, sentiments


@app.get("/", include_in_schema=False)
async def root():
    return {"api": "News Sentiment API", "version": "1.0.0", "docs": "/docs"}


@app.get(
    "/sentiment/{topic}",
    summary="Aggregate sentiment for any topic",
    description="Fetches recent news about a topic and returns aggregated sentiment with a -100 to +100 index.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_sentiment(
    topic: str,
    articles: int = Query(10, ge=1, le=20, description="Number of articles to analyze"),
):
    key = f"sent:{topic.lower()}:{articles}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    try:
        article_results, sentiments = await _articles_with_sentiment(topic, articles)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    if not article_results:
        raise HTTPException(status_code=404, detail=f"No recent news found for '{topic}'")

    aggregate = aggregate_sentiments(sentiments)

    payload = {
        "topic": topic,
        "aggregate_sentiment": aggregate,
        "articles": article_results,
        "analyzed_at": int(time.time()),
    }
    _cache.set(key, payload)
    return success(payload)


@app.get(
    "/headlines/{country}",
    summary="Top headlines with sentiment",
    description="Returns today's top headlines for a country (2-letter ISO code) with per-article sentiment.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_headlines(
    country: str,
    category: Optional[str] = Query(None, description="business, technology, sports, health, science, entertainment"),
):
    if not NEWS_API_KEY:
        raise HTTPException(status_code=503, detail="NEWS_API_KEY not configured — see /docs for setup")

    country = country.lower()[:2]
    key = f"headlines:{country}:{category}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    params = {
        "country": country,
        "pageSize": 15,
        "apiKey": NEWS_API_KEY,
    }
    if category:
        params["category"] = category

    try:
        r = await _client.get(f"{NEWS_API_BASE}/top-headlines", params=params)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    articles = data.get("articles", [])
    results = []
    sentiments = []
    for a in articles:
        text = f"{a.get('title', '')} {a.get('description', '')}".strip()
        if not text:
            continue
        sentiment = await hf_sentiment(_client, text)
        sentiments.append(sentiment)
        results.append({
            "title": a.get("title"),
            "description": a.get("description"),
            "source": a.get("source", {}).get("name"),
            "url": a.get("url"),
            "image": a.get("urlToImage"),
            "published_at": a.get("publishedAt"),
            "sentiment": sentiment,
        })

    aggregate = aggregate_sentiments(sentiments)

    payload = {
        "country": country,
        "category": category or "general",
        "aggregate_sentiment": aggregate,
        "headlines": results,
        "total": len(results),
        "fetched_at": int(time.time()),
    }
    _cache.set(key, payload)
    return success(payload)


@app.get(
    "/compare",
    summary="Compare sentiment across topics",
    description="Side-by-side sentiment comparison for up to 5 topics.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def compare_topics(
    topics: str = Query(..., description="Comma-separated topics, max 5"),
):
    topic_list = [t.strip() for t in topics.split(",") if t.strip()][:5]
    if len(topic_list) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 topics")

    results = []
    for topic in topic_list:
        key = f"sent:{topic.lower()}:5"
        cached = _cache.get(key)
        if cached:
            results.append({"topic": topic, "sentiment": cached["aggregate_sentiment"]})
            continue
        try:
            _, sentiments = await _articles_with_sentiment(topic, 5)
            aggregate = aggregate_sentiments(sentiments)
            results.append({"topic": topic, "sentiment": aggregate})
        except Exception:
            results.append({"topic": topic, "error": "fetch failed"})

    results.sort(key=lambda x: x.get("sentiment", {}).get("sentiment_index", 0), reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return success({"comparison": results, "most_positive": results[0]["topic"] if results else None})


class AnalyzeRequest(BaseModel):
    text: str
    batch: Optional[List[str]] = None


@app.post(
    "/analyze",
    summary="Analyze custom text",
    description="Analyze sentiment of any text or a batch of texts (max 20).",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def analyze_text(body: AnalyzeRequest):
    if body.batch:
        texts = body.batch[:20]
        results = []
        for text in texts:
            sentiment = await hf_sentiment(_client, text[:512])
            results.append({"text": text[:100] + "..." if len(text) > 100 else text, "sentiment": sentiment})
        aggregate = aggregate_sentiments([r["sentiment"] for r in results])
        return success({"results": results, "aggregate": aggregate})

    if not body.text:
        raise HTTPException(status_code=400, detail="Provide 'text' or 'batch'")
    sentiment = await hf_sentiment(_client, body.text[:512])
    return success({"text": body.text, "sentiment": sentiment})
