"""
LinkedIn Jobs API
-----------------
Search and explore LinkedIn public job listings. No LinkedIn account needed.

Endpoints:
  GET /search          Search jobs by keyword, location, filters
  GET /job/{job_id}    Full job details (description, criteria, skills)
  GET /trending        Sample of trending tech job categories
  GET /salary-insights Salary hint extraction for a search query
"""

import os
import sys
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional

from common.auth import verify_rapidapi_request
from common.cache import TTLCache
from common.response import success
from scraper import search_jobs, get_job_detail, BROWSER_HEADERS

_cache = TTLCache(maxsize=1000, ttl=600)  # 10-min default TTL
_client: httpx.AsyncClient = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(
        headers=BROWSER_HEADERS,
        timeout=20,
        follow_redirects=True,
    )
    yield
    await _client.aclose()


app = FastAPI(
    title="LinkedIn Jobs API",
    description=(
        "Search millions of LinkedIn public job listings by keyword, location, work type, "
        "and experience level. Get structured job details including full description, "
        "seniority, employment type, applicant count, and salary hints — no LinkedIn "
        "account or API key required."
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


def _handle_li_error(e: Exception) -> None:
    """Translate LinkedIn HTTP errors to FastAPI exceptions."""
    if isinstance(e, httpx.HTTPStatusError):
        sc = e.response.status_code
        if sc in (429, 999):
            raise HTTPException(
                status_code=429,
                detail="LinkedIn rate limit hit — please wait 60 seconds and retry.",
            )
        if sc == 404:
            raise HTTPException(status_code=404, detail="Job not found on LinkedIn.")
        raise HTTPException(status_code=503, detail=f"LinkedIn returned {sc}.")
    raise HTTPException(status_code=500, detail=str(e))


# ─── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    return {"api": "LinkedIn Jobs API", "version": "1.0.0", "docs": "/docs"}


@app.get(
    "/search",
    summary="Search LinkedIn jobs",
    description=(
        "Search public LinkedIn job listings. Returns up to 25 jobs per page. "
        "Filter by work type (remote/hybrid/onsite), experience level, date posted, "
        "and job type (full-time/part-time/contract/internship)."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def search(
    keywords: str = Query(..., description="Job title or skill keywords, e.g. 'Python Developer'"),
    location: str = Query("", description="City or country, e.g. 'India', 'New York'"),
    page: int = Query(0, ge=0, le=40, description="Page number (0-indexed, 25 results per page)"),
    work_type: Optional[str] = Query(
        None, description="Work arrangement: remote | hybrid | onsite"
    ),
    experience: Optional[str] = Query(
        None,
        description="Seniority: internship | entry | associate | mid-senior | director | executive",
    ),
    date_posted: Optional[str] = Query(
        None, description="Recency filter: day | week | month"
    ),
    job_type: Optional[str] = Query(
        None, description="Contract type: full-time | part-time | contract | internship"
    ),
):
    cache_key = f"search:{keywords}:{location}:{page}:{work_type}:{experience}:{date_posted}:{job_type}"
    hit = _cache.get(cache_key)
    if hit is not None:
        return success(hit, meta={"count": len(hit), "page": page, "cached": True})

    try:
        jobs = await search_jobs(
            _client, keywords, location, page, work_type, experience, date_posted, job_type
        )
    except Exception as e:
        _handle_li_error(e)

    _cache.set(cache_key, jobs)
    return success(
        jobs,
        meta={
            "count": len(jobs),
            "page": page,
            "keywords": keywords,
            "location": location or "worldwide",
            "cached": False,
        },
    )


@app.get(
    "/job/{job_id}",
    summary="Get full job details",
    description=(
        "Fetch complete details for a LinkedIn job posting by its numeric ID. "
        "Returns the full job description, seniority level, employment type, "
        "industry, applicant count, and any salary hints found in the posting."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def job_detail(job_id: str):
    if not job_id.isdigit():
        raise HTTPException(status_code=400, detail="job_id must be a numeric LinkedIn job ID.")

    cache_key = f"job:{job_id}"
    hit = _cache.get(cache_key)
    if hit is not None:
        return success(hit)

    try:
        detail = await get_job_detail(_client, job_id)
    except Exception as e:
        _handle_li_error(e)

    _cache.set(cache_key, detail, ttl=1800)  # 30-min TTL — job details change rarely
    return success(detail)


@app.get(
    "/trending",
    summary="Trending job categories",
    description=(
        "Returns live job counts and sample listings for the most in-demand "
        "tech and business roles on LinkedIn right now."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def trending():
    cache_key = "trending"
    hit = _cache.get(cache_key)
    if hit is not None:
        return success(hit)

    CATEGORIES = [
        ("AI Engineer", ""),
        ("Data Scientist", ""),
        ("Full Stack Developer", ""),
        ("DevOps Engineer", ""),
        ("Product Manager", ""),
        ("Prompt Engineer", ""),
        ("Machine Learning Engineer", ""),
        ("Cybersecurity Analyst", ""),
    ]

    results = []
    for keywords, location in CATEGORIES:
        try:
            jobs = await search_jobs(_client, keywords, location, page=0)
            results.append(
                {
                    "category": keywords,
                    "live_listing_count_sample": len(jobs),
                    "top_jobs": [
                        {k: j[k] for k in ("job_id", "title", "company", "location", "posted_ago")}
                        for j in jobs[:3]
                    ],
                }
            )
            await asyncio.sleep(0.4)  # polite delay
        except Exception:
            results.append({"category": keywords, "error": "temporarily unavailable"})

    _cache.set(cache_key, results, ttl=3600)  # cache for 1 hour
    return success(results)


@app.get(
    "/salary-insights",
    summary="Salary hints from job postings",
    description=(
        "Searches LinkedIn for jobs matching the keyword and extracts any salary "
        "figures mentioned in the postings. Useful for quick market salary research."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def salary_insights(
    keywords: str = Query(..., description="Job title, e.g. 'Python Developer'"),
    location: str = Query("", description="Optional location filter"),
):
    cache_key = f"salary:{keywords}:{location}"
    hit = _cache.get(cache_key)
    if hit is not None:
        return success(hit)

    try:
        jobs = await search_jobs(_client, keywords, location, page=0)
    except Exception as e:
        _handle_li_error(e)

    # Fetch details for first 5 jobs in parallel, extract salary hints
    job_ids = [j["job_id"] for j in jobs[:5] if j.get("job_id")]
    salary_data = []

    async def _fetch_salary(jid):
        try:
            detail = await get_job_detail(_client, jid)
            if detail.get("salary_hints"):
                return {
                    "job_id": jid,
                    "title": detail.get("title"),
                    "company": detail.get("company"),
                    "location": detail.get("location"),
                    "salary_hints": detail["salary_hints"],
                }
        except Exception:
            pass
        return None

    results = await asyncio.gather(*[_fetch_salary(jid) for jid in job_ids])
    salary_data = [r for r in results if r]

    out = {
        "keywords": keywords,
        "location": location or "worldwide",
        "jobs_scanned": len(job_ids),
        "jobs_with_salary_info": len(salary_data),
        "salary_data": salary_data,
    }
    _cache.set(cache_key, out, ttl=1800)
    return success(out)
