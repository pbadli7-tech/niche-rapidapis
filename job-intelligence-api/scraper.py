"""
LinkedIn Public Jobs Scraper
----------------------------
Uses LinkedIn's public guest-jobs API (no auth required).
Endpoints hit:
  Search : GET /jobs-guest/jobs/api/seeMoreJobPostings/search
  Detail : GET /jobs-guest/jobs/api/jobPosting/{job_id}
"""

import re
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

LI_BASE = "https://www.linkedin.com"
LI_JOBS_API = f"{LI_BASE}/jobs-guest/jobs/api"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.linkedin.com/jobs/",
}

WORK_TYPE_MAP = {"remote": 2, "hybrid": 3, "onsite": 1, "on-site": 1}
EXP_MAP = {
    "internship": 1,
    "entry": 2,
    "associate": 3,
    "mid-senior": 4,
    "director": 5,
    "executive": 6,
}
DATE_MAP = {"day": "r86400", "week": "r604800", "month": "r2592000"}


def _extract_job_id(text: str) -> Optional[str]:
    """Pull the numeric job ID from a URL or URN string."""
    m = re.search(r"(\d{9,})", text)
    return m.group(1) if m else None


def _parse_search_card(li_tag) -> Optional[Dict]:
    """Parse a single <li> job card from the search results HTML."""
    try:
        card = li_tag.find("div", class_="base-card")
        if not card:
            card = li_tag

        # Job ID from data-entity-urn or from the link href
        job_id = _extract_job_id(card.get("data-entity-urn", ""))
        link_el = card.find("a", href=re.compile(r"/jobs/view/"))
        if not job_id and link_el:
            job_id = _extract_job_id(link_el.get("href", ""))
        if not job_id:
            return None

        title_el = card.find(["h3", "h2"], class_=re.compile(r"base-search-card__title"))
        company_el = card.find(["h4", "span"], class_=re.compile(r"base-search-card__subtitle"))
        location_el = card.find(["span", "div"], class_=re.compile(r"job-search-card__location"))
        time_el = card.find("time")
        badge_el = card.find(["span", "div"], class_=re.compile(r"job-search-card__easy-apply-label|result-benefits"))
        img_el = card.find("img")

        # Clean up company text (remove nested link noise)
        company_text = None
        if company_el:
            company_text = company_el.get_text(" ", strip=True)

        # Company logo
        logo = None
        if img_el:
            logo = img_el.get("data-delayed-url") or img_el.get("data-ghost-url") or img_el.get("src")
            if logo and "ghost" in logo:
                logo = None  # placeholder ghost image

        # Clean job URL (strip tracking params)
        job_url = None
        if link_el:
            href = link_el.get("href", "")
            job_url = href.split("?")[0] if href else None

        return {
            "job_id": job_id,
            "title": title_el.get_text(strip=True) if title_el else None,
            "company": company_text,
            "location": location_el.get_text(strip=True) if location_el else None,
            "posted_at": time_el.get("datetime") if time_el else None,
            "posted_ago": time_el.get_text(strip=True) if time_el else None,
            "is_actively_hiring": bool(badge_el),
            "company_logo_url": logo,
            "job_url": job_url,
        }
    except Exception:
        return None


async def search_jobs(
    client: httpx.AsyncClient,
    keywords: str,
    location: str = "",
    page: int = 0,
    work_type: Optional[str] = None,
    experience: Optional[str] = None,
    date_posted: Optional[str] = None,
    job_type: Optional[str] = None,
) -> List[Dict]:
    """
    Search LinkedIn public job listings.

    Args:
        keywords    : Job title or skill, e.g. "Python Developer"
        location    : City/country, e.g. "India", "San Francisco, CA"
        page        : 0-indexed page (25 results per page)
        work_type   : "remote" | "hybrid" | "onsite"
        experience  : "internship" | "entry" | "associate" | "mid-senior" | "director" | "executive"
        date_posted : "day" | "week" | "month"
        job_type    : "full-time" | "part-time" | "contract" | "internship"
    """
    params: Dict = {
        "keywords": keywords,
        "location": location,
        "start": page * 25,
        "count": 25,
    }

    if work_type:
        wt = WORK_TYPE_MAP.get(work_type.lower())
        if wt:
            params["f_WT"] = wt

    if experience:
        exp = EXP_MAP.get(experience.lower())
        if exp:
            params["f_E"] = exp

    if date_posted:
        dp = DATE_MAP.get(date_posted.lower())
        if dp:
            params["f_TPR"] = dp

    jt_map = {"full-time": "F", "part-time": "P", "contract": "C", "internship": "I"}
    if job_type:
        jt = jt_map.get(job_type.lower())
        if jt:
            params["f_JT"] = jt

    r = await client.get(
        f"{LI_JOBS_API}/seeMoreJobPostings/search",
        params=params,
        headers=BROWSER_HEADERS,
    )

    if r.status_code == 429 or r.status_code == 999:
        raise httpx.HTTPStatusError("Rate limited", request=r.request, response=r)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    jobs = []
    for li in soup.find_all("li"):
        parsed = _parse_search_card(li)
        if parsed:
            jobs.append(parsed)

    return jobs


async def get_job_detail(client: httpx.AsyncClient, job_id: str) -> Dict:
    """Fetch full job detail from LinkedIn's public jobPosting endpoint."""
    r = await client.get(
        f"{LI_JOBS_API}/jobPosting/{job_id}",
        headers=BROWSER_HEADERS,
    )
    if r.status_code == 429 or r.status_code == 999:
        raise httpx.HTTPStatusError("Rate limited", request=r.request, response=r)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    # Title
    title_el = (
        soup.find("h2", class_=re.compile(r"top-card-layout__title"))
        or soup.find("h1", class_=re.compile(r"topcard__title"))
        or soup.find("h1")
    )

    # Company
    company_el = (
        soup.find("a", class_=re.compile(r"topcard__org-name-link"))
        or soup.find("span", class_=re.compile(r"topcard__org-name"))
        or soup.find("a", class_=re.compile(r"topcard__flavor"))
    )

    # Location — look for topcard__flavor--bullet specifically, fall back to any flavor != company
    location_el = (
        soup.find(["span", "div"], class_=re.compile(r"topcard__flavor--bullet"))
        or soup.find(["span", "div"], class_=re.compile(r"topcard__flavor--black"))
    )
    if not location_el:
        for el in soup.find_all(["span", "div"], class_=re.compile(r"topcard__flavor")):
            if el != company_el and el.get_text(strip=True):
                location_el = el
                break

    # Applicant count
    applicant_el = soup.find(
        ["span", "figcaption", "div"],
        class_=re.compile(r"num-applicants__caption|applicant-count"),
    )
    if not applicant_el:
        # Fall back: look for text containing "applicants"
        for el in soup.find_all(["span", "div"]):
            txt = el.get_text(strip=True)
            if "applicant" in txt.lower() and len(txt) < 60:
                applicant_el = el
                break

    # Job description
    desc_el = soup.find("div", class_=re.compile(r"show-more-less-html__markup"))
    if not desc_el:
        desc_el = soup.find("div", class_=re.compile(r"description__text"))
    description = desc_el.get_text("\n", strip=True) if desc_el else ""

    # Structured criteria (Seniority, Employment type, Job function, Industry)
    criteria: Dict[str, str] = {}
    for item in soup.find_all("li", class_=re.compile(r"description__job-criteria-item")):
        label_el = item.find(["h3", "span"], class_=re.compile(r"description__job-criteria-subheader"))
        value_el = item.find(["span"], class_=re.compile(r"description__job-criteria-text"))
        if label_el and value_el:
            key = label_el.get_text(strip=True).lower().replace(" ", "_")
            criteria[key] = value_el.get_text(strip=True)

    # Skills mentioned (if LinkedIn surfaces them)
    skills: List[str] = []
    for el in soup.find_all(["span", "a"], class_=re.compile(r"job-criteria__text|skill-pill")):
        t = el.get_text(strip=True)
        if t and t not in skills:
            skills.append(t)

    # Salary hints (regex on description)
    salary_hints: List[str] = []
    if description:
        patterns = [
            r"\$[\d,]+(?:\s*[-–]\s*\$[\d,]+)?(?:\s*/\s*(?:yr|year|hr|hour|month|annum))?",
            r"₹\s*[\d,]+(?:\s*[-–]\s*₹\s*[\d,]+)?(?:\s*(?:LPA|per\s+annum|/month))?",
            r"\b\d+(?:\.\d+)?\s*LPA\b",
            r"\b[\d,]+\s*(?:USD|INR|GBP|EUR)\b",
        ]
        for pat in patterns:
            for m in re.findall(pat, description, re.IGNORECASE):
                if m.strip() not in salary_hints:
                    salary_hints.append(m.strip())

    # Company logo
    logo_el = soup.find("img", class_=re.compile(r"artdeco-entity-image|top-card__logo"))
    logo_url = None
    if logo_el:
        logo_url = logo_el.get("data-delayed-url") or logo_el.get("src")
        if logo_url and "ghost" in logo_url:
            logo_url = None

    return {
        "job_id": job_id,
        "title": title_el.get_text(strip=True) if title_el else None,
        "company": company_el.get_text(strip=True) if company_el else None,
        "location": location_el.get_text(strip=True) if location_el else None,
        "applicants": applicant_el.get_text(strip=True) if applicant_el else None,
        "description": description[:4000] if description else None,
        "criteria": criteria,
        "skills": skills[:20],
        "salary_hints": salary_hints[:5],
        "company_logo_url": logo_url,
        "apply_url": f"https://www.linkedin.com/jobs/view/{job_id}",
    }
