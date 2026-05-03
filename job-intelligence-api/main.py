"""
Job Market Intelligence API
-----------------------------
Transforms raw LinkedIn job listings into structured market intelligence:
  GET /overview     — Market snapshot: job counts, work-type mix, top companies, competitiveness
  GET /skills       — Top skills ranked by demand frequency across job descriptions
  GET /salary       — Salary percentiles and ranges extracted from job postings
  GET /companies    — Top hiring companies with open position counts
  GET /compare      — Side-by-side comparison of up to 3 job titles
  GET /trending     — Fastest-growing roles in a location (by posting volume)
"""

import asyncio

import httpx
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional, List

from common.auth import verify_rapidapi_request
from common.cache import TTLCache
from common.response import success

# Import LinkedIn scraper (copied into this service)
from scraper import search_jobs, get_job_detail, BROWSER_HEADERS
from analyzer import (
    build_market_overview,
    build_skills_demand,
    build_salary_intelligence,
    build_companies_report,
)

# ─── Cache & HTTP client ──────────────────────────────────────────────────────
_cache = TTLCache(maxsize=500, ttl=3600)  # 1-hour default — intelligence queries are expensive
_client: httpx.AsyncClient = None

DETAIL_FETCH_COUNT = 10   # How many job details to fetch per intelligence query
SEARCH_PAGE_COUNT = 1     # Pages of search results to aggregate (25 results each)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(
        headers=BROWSER_HEADERS,
        timeout=25,
        follow_redirects=True,
    )
    yield
    await _client.aclose()


app = FastAPI(
    title="Job Market Intelligence API",
    description=(
        "Transform raw job listings into actionable market intelligence. "
        "Get real-time salary ranges, in-demand skills, top hiring companies, "
        "and market competitiveness scores for any job title and location. "
        "Powered by live LinkedIn public data — no authentication required."
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


# ─── Shared data fetcher ──────────────────────────────────────────────────────

async def _fetch_intelligence_data(
    job_title: str,
    location: str,
    pages: int = SEARCH_PAGE_COUNT,
    detail_count: int = DETAIL_FETCH_COUNT,
) -> tuple[list, list]:
    """
    Search LinkedIn for job_title+location across N pages, then fetch details
    for the top `detail_count` results. Returns (search_results, details).
    """
    # Fetch search results (potentially multiple pages)
    all_results = []
    for page in range(pages):
        try:
            results = await search_jobs(_client, job_title, location, page=page)
            all_results.extend(results)
            if results:
                await asyncio.sleep(0.3)  # polite delay
        except Exception:
            break

    if not all_results:
        return [], []

    # Fetch details for top N jobs in parallel
    job_ids = [j["job_id"] for j in all_results[:detail_count] if j.get("job_id")]

    async def _safe_detail(jid: str):
        try:
            return await get_job_detail(_client, jid)
        except Exception:
            return None

    raw_details = await asyncio.gather(*[_safe_detail(jid) for jid in job_ids])
    details = [d for d in raw_details if d]

    return all_results, details


def _handle_li_error(e: Exception) -> None:
    if isinstance(e, httpx.HTTPStatusError):
        sc = e.response.status_code
        if sc in (429, 999):
            raise HTTPException(
                status_code=429,
                detail="LinkedIn rate limit hit — please wait 60 seconds and retry.",
            )
        raise HTTPException(status_code=503, detail=f"LinkedIn returned {sc}.")
    raise HTTPException(status_code=500, detail=str(e))


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    return {"api": "Job Market Intelligence API", "version": "1.0.0", "docs": "/docs"}


@app.get(
    "/overview",
    summary="Job market overview",
    description=(
        "Get a comprehensive market snapshot for any job title and location: "
        "total active jobs, work-type breakdown (remote/hybrid/onsite), "
        "top hiring companies, posting recency, experience level distribution, "
        "and a market competitiveness score."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def market_overview(
    job_title: str = Query(..., description="Job title to analyze, e.g. 'Python Developer'"),
    location: str = Query("", description="Location filter, e.g. 'India', 'New York'. Leave empty for worldwide."),
):
    cache_key = f"overview:{job_title.lower()}:{location.lower()}"
    hit = _cache.get(cache_key)
    if hit is not None:
        return success(hit, meta={"cached": True})

    try:
        search_results, details = await _fetch_intelligence_data(job_title, location)
    except Exception as e:
        _handle_li_error(e)

    if not search_results:
        raise HTTPException(status_code=404, detail=f"No jobs found for '{job_title}' in '{location or 'worldwide'}'.")

    data = build_market_overview(job_title, location, search_results, details)
    _cache.set(cache_key, data)
    return success(data, meta={"cached": False, "jobs_fetched": len(search_results), "details_fetched": len(details)})


@app.get(
    "/skills",
    summary="In-demand skills for a job title",
    description=(
        "Discover the top skills employers are asking for in a given role. "
        "Returns skills ranked by demand frequency (how often they appear across job descriptions), "
        "grouped by category: programming languages, frameworks, cloud/DevOps, AI/ML, etc."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def skills_demand(
    job_title: str = Query(..., description="Job title, e.g. 'Data Scientist'"),
    location: str = Query("", description="Location filter. Leave empty for worldwide."),
    limit: int = Query(20, ge=5, le=30, description="Number of top skills to return (5-30)"),
):
    cache_key = f"skills:{job_title.lower()}:{location.lower()}"
    hit = _cache.get(cache_key)
    if hit is not None:
        data = {**hit, "top_skills": hit["top_skills"][:limit]}
        return success(data, meta={"cached": True})

    try:
        _, details = await _fetch_intelligence_data(job_title, location)
    except Exception as e:
        _handle_li_error(e)

    if not details:
        raise HTTPException(status_code=404, detail=f"No job details found for '{job_title}'.")

    data = build_skills_demand(job_title, location, details)
    _cache.set(cache_key, data)
    data = {**data, "top_skills": data["top_skills"][:limit]}
    return success(data, meta={"cached": False, "jobs_analyzed": len(details)})


@app.get(
    "/salary",
    summary="Salary intelligence and percentiles",
    description=(
        "Extract salary ranges and percentiles from job postings for a given role and location. "
        "Returns P25/P50/P75 salary percentiles, min/max range, and the raw salary mentions found. "
        "Supports USD, INR (LPA), GBP, and EUR. Confidence is higher with more data points."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def salary_intelligence(
    job_title: str = Query(..., description="Job title, e.g. 'Software Engineer'"),
    location: str = Query("", description="Location filter. More specific = more relevant salary data."),
):
    cache_key = f"salary:{job_title.lower()}:{location.lower()}"
    hit = _cache.get(cache_key)
    if hit is not None:
        return success(hit, meta={"cached": True})

    try:
        _, details = await _fetch_intelligence_data(job_title, location, detail_count=15)
    except Exception as e:
        _handle_li_error(e)

    if not details:
        raise HTTPException(status_code=404, detail=f"No job details found for '{job_title}'.")

    data = build_salary_intelligence(job_title, location, details)
    _cache.set(cache_key, data)
    return success(data, meta={"cached": False, "jobs_analyzed": len(details)})


@app.get(
    "/companies",
    summary="Top hiring companies for a role",
    description=(
        "Identify which companies are actively hiring for a given role and location. "
        "Returns companies ranked by number of open positions in the current sample, "
        "with industry info and sample job titles."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def top_companies(
    job_title: str = Query(..., description="Job title, e.g. 'DevOps Engineer'"),
    location: str = Query("", description="Location filter. Leave empty for worldwide."),
):
    cache_key = f"companies:{job_title.lower()}:{location.lower()}"
    hit = _cache.get(cache_key)
    if hit is not None:
        return success(hit, meta={"cached": True})

    try:
        search_results, details = await _fetch_intelligence_data(job_title, location)
    except Exception as e:
        _handle_li_error(e)

    if not search_results:
        raise HTTPException(status_code=404, detail=f"No jobs found for '{job_title}'.")

    data = build_companies_report(job_title, location, search_results, details)
    _cache.set(cache_key, data)
    return success(data, meta={"cached": False})


@app.get(
    "/compare",
    summary="Compare multiple job titles side-by-side",
    description=(
        "Compare up to 3 job titles for a given location. Returns a side-by-side breakdown "
        "of active job count, top skills, remote-friendliness, and market competitiveness. "
        "Perfect for career decisions: 'Should I be a Data Scientist or ML Engineer?'"
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def compare_roles(
    titles: str = Query(
        ...,
        description="Comma-separated job titles (2-3), e.g. 'Python Developer,Java Developer,Go Developer'",
    ),
    location: str = Query("", description="Location filter applied to all titles."),
):
    title_list = [t.strip() for t in titles.split(",") if t.strip()][:3]
    if len(title_list) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 comma-separated job titles.")

    cache_key = f"compare:{','.join(t.lower() for t in title_list)}:{location.lower()}"
    hit = _cache.get(cache_key)
    if hit is not None:
        return success(hit, meta={"cached": True})

    async def _analyze_one(title: str) -> dict:
        try:
            search_results, details = await _fetch_intelligence_data(title, location, detail_count=8)
            overview = build_market_overview(title, location, search_results, details)
            skills_data = build_skills_demand(title, location, details)
            return {
                "job_title": title,
                "active_jobs_in_sample": overview.get("total_jobs_in_sample", 0),
                "remote_friendly": overview.get("remote_friendly", False),
                "market_competitiveness": overview.get("market_competitiveness", "unknown"),
                "work_type_breakdown": overview.get("work_type_breakdown", {}),
                "top_5_skills": [s["skill"] for s in skills_data.get("top_skills", [])[:5]],
                "most_in_demand_skill": skills_data.get("most_in_demand"),
                "top_hiring_companies": [
                    c["company"] for c in overview.get("top_hiring_companies", [])[:5]
                ],
            }
        except Exception:
            return {"job_title": title, "error": "data temporarily unavailable"}

    # Fetch in parallel with a small delay between to avoid rate limits
    results = []
    for i, title in enumerate(title_list):
        if i > 0:
            await asyncio.sleep(1.0)
        result = await _analyze_one(title)
        results.append(result)

    data = {
        "location": location or "worldwide",
        "comparison": results,
    }
    _cache.set(cache_key, data)
    return success(data, meta={"cached": False, "titles_compared": len(results)})


@app.get(
    "/trending",
    summary="Trending job roles by posting volume",
    description=(
        "Discover which tech and business roles have the most active job postings right now. "
        "Returns a ranked list of popular roles with live job counts, top skills, and "
        "remote-friendliness indicators — updated hourly."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def trending_roles(
    location: str = Query("", description="Location filter, e.g. 'India', 'United States'. Leave empty for worldwide."),
    category: Optional[str] = Query(
        None,
        description="Filter by role category: tech | data | business | design | all (default: all)",
    ),
):
    cache_key = f"trending:{location.lower()}:{(category or 'all').lower()}"
    hit = _cache.get(cache_key)
    if hit is not None:
        return success(hit, meta={"cached": True})

    ROLES_BY_CATEGORY = {
        "tech": [
            "Software Engineer", "Full Stack Developer", "Backend Developer",
            "Frontend Developer", "DevOps Engineer", "Cloud Engineer",
            "Site Reliability Engineer", "Mobile Developer",
        ],
        "data": [
            "Data Scientist", "Data Engineer", "Data Analyst",
            "Machine Learning Engineer", "AI Engineer", "Business Intelligence Analyst",
        ],
        "business": [
            "Product Manager", "Project Manager", "Business Analyst",
            "Scrum Master", "Technical Program Manager",
        ],
        "design": [
            "UI/UX Designer", "Product Designer", "UX Researcher",
        ],
    }

    if category and category.lower() in ROLES_BY_CATEGORY:
        roles_to_check = ROLES_BY_CATEGORY[category.lower()]
    else:
        # All categories — pick top roles from each
        roles_to_check = [
            "Software Engineer", "Data Scientist", "Full Stack Developer",
            "DevOps Engineer", "Product Manager", "Machine Learning Engineer",
            "Data Engineer", "Cloud Engineer", "AI Engineer", "UI/UX Designer",
        ]

    results = []
    for i, role in enumerate(roles_to_check):
        if i > 0:
            await asyncio.sleep(0.5)
        try:
            search_results, details = await _fetch_intelligence_data(role, location, detail_count=5)
            skills_data = build_skills_demand(role, location, details)
            overview = build_market_overview(role, location, search_results, details)
            results.append({
                "rank": i + 1,
                "role": role,
                "active_jobs_sample": overview.get("total_jobs_in_sample", 0),
                "remote_friendly": overview.get("remote_friendly", False),
                "market_competitiveness": overview.get("market_competitiveness", "unknown"),
                "top_3_skills": [s["skill"] for s in skills_data.get("top_skills", [])[:3]],
                "work_type_breakdown": overview.get("work_type_breakdown", {}),
            })
        except Exception:
            results.append({"rank": i + 1, "role": role, "error": "temporarily unavailable"})

    # Re-rank by active_jobs_sample
    valid = [r for r in results if "active_jobs_sample" in r]
    errors = [r for r in results if "error" in r]
    valid.sort(key=lambda x: -x["active_jobs_sample"])
    for i, r in enumerate(valid):
        r["rank"] = i + 1

    data = {
        "location": location or "worldwide",
        "category": category or "all",
        "trending_roles": valid + errors,
    }
    _cache.set(cache_key, data, ttl=3600)
    return success(data, meta={"cached": False, "roles_analyzed": len(valid)})
