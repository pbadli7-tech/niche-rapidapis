"""
Job Market Intelligence Analyzer
----------------------------------
Aggregates raw LinkedIn job search + detail data into structured market intelligence:
  - Market overview (job counts, work-type breakdown, recency, competitiveness)
  - Skills demand (frequency ranking across job descriptions)
  - Salary intelligence (percentile distribution from salary hints)
  - Top hiring companies
"""

import re
import statistics
from collections import Counter
from typing import Dict, List, Optional, Tuple

from skills_db import extract_skills, get_category, SKILLS_DB


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _infer_work_type(job: dict, detail: Optional[dict] = None) -> Optional[str]:
    """Guess work type from search card + optional detail criteria."""
    # Check detail criteria first
    if detail:
        et = detail.get("criteria", {}).get("employment_type", "")
        loc = detail.get("location", "") or ""
        desc = detail.get("description", "") or ""
        text = f"{et} {loc} {desc}".lower()
    else:
        text = (job.get("title", "") + " " + job.get("location", "")).lower()

    if "remote" in text:
        return "remote"
    if "hybrid" in text:
        return "hybrid"
    if any(w in text for w in ["on-site", "onsite", "in-office", "in office"]):
        return "onsite"
    return None


def _parse_salary_value(hint: str) -> Optional[float]:
    """
    Convert a salary hint string to a numeric value (in thousands for USD, LPA for INR).
    Returns None if unparseable.
    """
    hint = hint.strip()
    # LPA (Indian salary in lakhs)
    m = re.search(r"(\d+(?:\.\d+)?)\s*LPA", hint, re.IGNORECASE)
    if m:
        return float(m.group(1))

    # ₹ range → average
    m = re.search(r"₹\s*([\d,]+)\s*[-–]\s*₹\s*([\d,]+)", hint)
    if m:
        lo = float(m.group(1).replace(",", ""))
        hi = float(m.group(2).replace(",", ""))
        # Convert to LPA if values look monthly (< 1,00,000)
        avg = (lo + hi) / 2
        if avg < 200000:
            return round(avg * 12 / 100000, 1)  # monthly → annual LPA
        return round(avg / 100000, 1)

    # $ range → average in K USD
    m = re.search(r"\$([\d,]+)\s*[-–]\s*\$([\d,]+)", hint)
    if m:
        lo = float(m.group(1).replace(",", ""))
        hi = float(m.group(2).replace(",", ""))
        return round((lo + hi) / 2 / 1000, 1)

    # Single $ value
    m = re.search(r"\$([\d,]+)", hint)
    if m:
        val = float(m.group(1).replace(",", ""))
        return round(val / 1000, 1)

    return None


def _detect_currency(hints: List[str]) -> str:
    all_text = " ".join(hints)
    if "₹" in all_text or "LPA" in all_text.upper() or "INR" in all_text:
        return "INR"
    if "$" in all_text or "USD" in all_text:
        return "USD"
    if "£" in all_text or "GBP" in all_text:
        return "GBP"
    if "€" in all_text or "EUR" in all_text:
        return "EUR"
    return "UNKNOWN"


def _competitiveness(avg_applicants: Optional[str], job_count: int) -> str:
    """Rough competitiveness label."""
    if avg_applicants:
        m = re.search(r"(\d+)", avg_applicants.replace(",", ""))
        if m:
            n = int(m.group(1))
            if n > 200:
                return "very_high"
            if n > 100:
                return "high"
            if n > 50:
                return "medium"
            return "low"
    if job_count > 20:
        return "high"
    if job_count > 10:
        return "medium"
    return "low"


# ─── Core aggregation functions ───────────────────────────────────────────────

def build_market_overview(
    job_title: str,
    location: str,
    search_results: List[dict],
    details: List[dict],
) -> dict:
    """
    Aggregate search results + details into a market overview snapshot.
    """
    total = len(search_results)
    if total == 0:
        return {"job_title": job_title, "location": location, "total_jobs_found": 0}

    # Work type breakdown
    work_types: Counter = Counter()
    for job in search_results:
        wt = _infer_work_type(job)
        if wt:
            work_types[wt] += 1

    # Experience level from criteria
    exp_levels: Counter = Counter()
    for d in details:
        sl = d.get("criteria", {}).get("seniority_level", "")
        if sl:
            exp_levels[sl.lower().replace("-", "_").replace(" ", "_")] += 1

    # Top hiring companies
    company_counter: Counter = Counter()
    for job in search_results:
        c = job.get("company")
        if c:
            company_counter[c] += 1
    top_companies = [
        {"company": name, "open_jobs_in_sample": count}
        for name, count in company_counter.most_common(10)
    ]

    # Posting recency (from posted_at datetime or posted_ago text)
    recency: Counter = Counter({"last_24h": 0, "last_week": 0, "older": 0})
    for job in search_results:
        ago = (job.get("posted_ago") or "").lower()
        if any(w in ago for w in ["hour", "just now", "today"]):
            recency["last_24h"] += 1
        elif any(w in ago for w in ["day", "week"]):
            recency["last_week"] += 1
        else:
            recency["older"] += 1

    # Applicants — from details
    applicant_texts = [d.get("applicants") for d in details if d.get("applicants")]
    avg_applicants_text = applicant_texts[0] if applicant_texts else None

    # Remote-friendliness score
    remote_count = work_types.get("remote", 0) + work_types.get("hybrid", 0)
    remote_friendly = remote_count > (total * 0.3)

    # Industries from detail criteria
    industries: Counter = Counter()
    for d in details:
        ind = d.get("criteria", {}).get("industries", "") or d.get("criteria", {}).get("industry", "")
        if ind:
            industries[ind] += 1

    competitiveness = _competitiveness(avg_applicants_text, total)

    return {
        "job_title": job_title,
        "location": location or "worldwide",
        "total_jobs_in_sample": total,
        "work_type_breakdown": {
            "remote": work_types.get("remote", 0),
            "hybrid": work_types.get("hybrid", 0),
            "onsite": work_types.get("onsite", 0),
            "not_specified": total - sum(work_types.values()),
        },
        "experience_level_breakdown": dict(exp_levels.most_common()),
        "top_industries": [ind for ind, _ in industries.most_common(5)],
        "top_hiring_companies": top_companies,
        "posting_recency": dict(recency),
        "remote_friendly": remote_friendly,
        "market_competitiveness": competitiveness,
        "sample_applicants_info": avg_applicants_text,
    }


def build_skills_demand(
    job_title: str,
    location: str,
    details: List[dict],
) -> dict:
    """Extract and rank skills from job descriptions."""
    all_skills: Counter = Counter()
    jobs_analyzed = len(details)

    for d in details:
        desc = d.get("description", "") or ""
        # Also check skills field from scraper
        raw_skills = d.get("skills", [])

        skills_from_desc = extract_skills(desc)
        skills_from_field = []
        for s in raw_skills:
            from skills_db import _SKILL_LOOKUP
            canonical = _SKILL_LOOKUP.get(s.lower())
            if canonical:
                skills_from_field.append(canonical)

        # Union of both sources (per job, count skill once)
        job_skills = set(skills_from_desc) | set(skills_from_field)
        for skill in job_skills:
            all_skills[skill] += 1

    if jobs_analyzed == 0:
        return {"job_title": job_title, "location": location, "jobs_analyzed": 0, "top_skills": []}

    # Build ranked list
    top_skills = [
        {
            "skill": skill,
            "jobs_requiring": count,
            "percentage": round(count / jobs_analyzed * 100),
            "category": get_category(skill),
        }
        for skill, count in all_skills.most_common(30)
    ]

    # Grouped by category
    by_category: Dict[str, List[str]] = {}
    for skill, count in all_skills.most_common(50):
        cat = get_category(skill)
        if cat not in by_category:
            by_category[cat] = []
        if len(by_category[cat]) < 8:
            by_category[cat].append(skill)

    return {
        "job_title": job_title,
        "location": location or "worldwide",
        "jobs_analyzed": jobs_analyzed,
        "top_skills": top_skills,
        "skills_by_category": by_category,
        "most_in_demand": top_skills[0]["skill"] if top_skills else None,
    }


def build_salary_intelligence(
    job_title: str,
    location: str,
    details: List[dict],
) -> dict:
    """Aggregate salary hints into percentiles and ranges."""
    all_hints: List[str] = []
    jobs_with_salary = 0
    salary_values: List[float] = []

    for d in details:
        hints = d.get("salary_hints", [])
        if hints:
            jobs_with_salary += 1
            all_hints.extend(hints)
            for h in hints:
                val = _parse_salary_value(h)
                if val and val > 0:
                    salary_values.append(val)

    currency = _detect_currency(all_hints) if all_hints else "UNKNOWN"
    unit = "LPA" if currency == "INR" else "K USD" if currency in ("USD",) else ""

    result: dict = {
        "job_title": job_title,
        "location": location or "worldwide",
        "jobs_analyzed": len(details),
        "jobs_with_explicit_salary": jobs_with_salary,
        "currency": currency,
        "salary_unit": unit,
        "raw_salary_mentions": list(set(all_hints))[:10],
    }

    if len(salary_values) >= 3:
        salary_values_sorted = sorted(salary_values)
        n = len(salary_values_sorted)

        def percentile(data, p):
            idx = (p / 100) * (len(data) - 1)
            lo, hi = int(idx), min(int(idx) + 1, len(data) - 1)
            return round(data[lo] + (data[hi] - data[lo]) * (idx - lo), 1)

        result["salary_range"] = {
            "min": salary_values_sorted[0],
            "max": salary_values_sorted[-1],
        }
        result["percentiles"] = {
            "p25": percentile(salary_values_sorted, 25),
            "p50": percentile(salary_values_sorted, 50),
            "p75": percentile(salary_values_sorted, 75),
        }
        result["median_salary"] = percentile(salary_values_sorted, 50)
        result["data_confidence"] = "medium" if jobs_with_salary >= 5 else "low"
    else:
        result["note"] = (
            f"Only {jobs_with_salary} job(s) in this sample listed explicit salary data. "
            "Try a broader location or different keywords for more salary data."
        )
        result["data_confidence"] = "insufficient"

    return result


def build_companies_report(
    job_title: str,
    location: str,
    search_results: List[dict],
    details: List[dict],
) -> dict:
    """Rank companies by number of open positions."""
    company_jobs: Dict[str, list] = {}

    for job in search_results:
        company = job.get("company")
        if not company:
            continue
        if company not in company_jobs:
            company_jobs[company] = []
        company_jobs[company].append({
            "job_id": job.get("job_id"),
            "title": job.get("title"),
            "location": job.get("location"),
            "posted_ago": job.get("posted_ago"),
            "job_url": job.get("job_url"),
        })

    # Enrich with detail info for companies we have details for
    detail_by_id = {d.get("job_id"): d for d in details if d.get("job_id")}

    ranked = sorted(company_jobs.items(), key=lambda x: -len(x[1]))
    top_companies = []
    for company, jobs in ranked[:15]:
        # Get any detail for this company
        detail_info = {}
        for j in jobs:
            jid = j.get("job_id")
            if jid and jid in detail_by_id:
                d = detail_by_id[jid]
                detail_info = {
                    "industry": d.get("criteria", {}).get("industries", "") or d.get("criteria", {}).get("industry", ""),
                    "company_logo_url": d.get("company_logo_url"),
                }
                break

        top_companies.append({
            "company": company,
            "open_positions_in_sample": len(jobs),
            "sample_roles": [j["title"] for j in jobs[:3]],
            **detail_info,
        })

    return {
        "job_title": job_title,
        "location": location or "worldwide",
        "total_companies_hiring": len(company_jobs),
        "top_hiring_companies": top_companies,
    }
