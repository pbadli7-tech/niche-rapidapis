"""
Website SEO & Intelligence API
--------------------------------
Analyse any public URL for SEO metadata, technology stack, social tags,
performance hints, and robots/sitemap discovery — no API key required.

Endpoints
  GET /analyze?url=...     Full SEO + tech + social + performance report
  GET /meta?url=...        All meta tags (title, description, OG, Twitter, etc.)
  GET /tech?url=...        Technology stack fingerprinting
  GET /social?url=...      Open Graph + Twitter Card tags
  GET /headers?url=...     HTTP response headers and security grade
  GET /sitemap?domain=...  Discover sitemap(s) via robots.txt or common paths
"""
import os
import sys
import re
import time
import ssl
import socket
from typing import Optional
from urllib.parse import urljoin, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from bs4 import BeautifulSoup

from common.auth import verify_rapidapi_request
from common.cache import TTLCache
from common.response import success

_cache = TTLCache(maxsize=500, ttl=300)
_client: httpx.AsyncClient = None

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; WebSEOBot/1.0; "
        "+https://rapidapi.com)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

TECH_SIGNATURES = {
    # CMS
    "WordPress": [r"wp-content/", r"wp-includes/", r'generator.*wordpress', r'/wp-json/'],
    "Joomla": [r"joomla", r"/media/jui/"],
    "Drupal": [r"drupal", r"/sites/default/files/"],
    "Shopify": [r"cdn\.shopify\.com", r"Shopify\.theme"],
    "Magento": [r"mage/", r"Magento"],
    "Wix": [r"wix\.com", r"X-Wix-"],
    "Squarespace": [r"squarespace\.com", r"static\.squarespace"],
    "Webflow": [r"webflow\.com", r"\.webflow\."],
    # JS Frameworks
    "React": [r"react\.development\.js", r"react\.production\.min\.js", r"__REACT"],
    "Next.js": [r"_next/static", r"next\.js", r"__NEXT_DATA__"],
    "Vue.js": [r"vue\.js", r"vue\.min\.js", r"__vue__"],
    "Angular": [r"angular", r"ng-version"],
    "Nuxt.js": [r"_nuxt/", r"__nuxt"],
    "Gatsby": [r"gatsby", r"___gatsby"],
    "Svelte": [r"svelte"],
    # Analytics / Marketing
    "Google Analytics": [r"google-analytics\.com", r"gtag\(", r"UA-\d+"],
    "Google Tag Manager": [r"googletagmanager\.com", r"GTM-"],
    "Facebook Pixel": [r"connect\.facebook\.net", r"fbevents\.js"],
    "Hotjar": [r"hotjar\.com", r"hotjar"],
    "Intercom": [r"intercom\.io", r"Intercom"],
    "HubSpot": [r"js\.hs-analytics\.net", r"hubspot"],
    "Zendesk": [r"zendesk\.com", r"zdassets\.com"],
    # CDN / Hosting
    "Cloudflare": [r"cloudflare"],
    "AWS CloudFront": [r"cloudfront\.net"],
    "Fastly": [r"fastly\.net"],
    "Vercel": [r"vercel\.app", r"x-vercel"],
    "Netlify": [r"netlify\.app", r"x-nf-"],
    # Other
    "Bootstrap": [r"bootstrap\.min\.css", r"bootstrap\.min\.js"],
    "Tailwind CSS": [r"tailwind", r"tailwindcss"],
    "jQuery": [r"jquery\.min\.js", r"jquery-\d"],
    "Font Awesome": [r"font-awesome", r"fontawesome"],
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(
        headers=HEADERS,
        timeout=15,
        follow_redirects=True,
        verify=False,  # skip SSL verify for broad coverage
    )
    yield
    await _client.aclose()


app = FastAPI(
    title="Website SEO & Intelligence API",
    description=(
        "Instantly analyse any public website for SEO health, meta tags, technology stack, "
        "Open Graph / Twitter Card tags, HTTP security headers, and sitemap discovery. "
        "Perfect for marketers, SEO tools, and competitive research."
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


def _normalise_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _extract_meta(soup: BeautifulSoup, html: str, response: httpx.Response) -> dict:
    """Extract comprehensive meta information from a page."""
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

    def get_meta(name=None, prop=None, attrs=None):
        if name:
            tag = soup.find("meta", attrs={"name": name})
        elif prop:
            tag = soup.find("meta", attrs={"property": prop})
        elif attrs:
            tag = soup.find("meta", attrs=attrs)
        else:
            return None
        return tag.get("content") if tag else None

    canonical = None
    canon_tag = soup.find("link", rel="canonical")
    if canon_tag:
        canonical = canon_tag.get("href")

    robots_meta = get_meta(name="robots")
    viewport = get_meta(name="viewport")
    charset_tag = soup.find("meta", attrs={"charset": True})
    charset = charset_tag.get("charset") if charset_tag else None

    lang = soup.find("html", attrs={"lang": True})
    language = lang.get("lang") if lang else None

    h1_tags = [h.get_text(strip=True) for h in soup.find_all("h1")]
    h2_tags = [h.get_text(strip=True) for h in soup.find_all("h2")][:5]

    images = soup.find_all("img")
    images_without_alt = sum(1 for img in images if not img.get("alt"))

    links = soup.find_all("a", href=True)
    internal_links = []
    external_links = []
    base_domain = urlparse(str(response.url)).netloc
    for link in links[:200]:
        href = link.get("href", "")
        if href.startswith("http"):
            parsed = urlparse(href)
            if parsed.netloc == base_domain:
                internal_links.append(href)
            else:
                external_links.append(href)
        elif href.startswith("/"):
            internal_links.append(href)

    word_count = len(re.sub(r"\s+", " ", soup.get_text(separator=" ")).split())

    return {
        "title": title,
        "title_length": len(title) if title else 0,
        "description": get_meta(name="description"),
        "keywords": get_meta(name="keywords"),
        "canonical_url": canonical,
        "robots": robots_meta,
        "viewport": viewport,
        "charset": charset,
        "language": language,
        "h1_tags": h1_tags,
        "h2_tags": h2_tags,
        "total_images": len(images),
        "images_missing_alt": images_without_alt,
        "internal_links_count": len(set(internal_links)),
        "external_links_count": len(set(external_links)),
        "word_count": word_count,
    }


def _extract_og(soup: BeautifulSoup) -> dict:
    og = {}
    for tag in soup.find_all("meta", attrs={"property": re.compile(r"^og:")}):
        key = tag.get("property", "").replace("og:", "")
        og[key] = tag.get("content")

    twitter = {}
    for tag in soup.find_all("meta", attrs={"name": re.compile(r"^twitter:")}):
        key = tag.get("name", "").replace("twitter:", "")
        twitter[key] = tag.get("content")

    return {"open_graph": og, "twitter_card": twitter}


def _detect_tech(html: str, headers: dict) -> list:
    combined = html + " " + " ".join(f"{k}: {v}" for k, v in headers.items())
    found = []
    for tech, patterns in TECH_SIGNATURES.items():
        for pat in patterns:
            if re.search(pat, combined, re.IGNORECASE):
                found.append(tech)
                break
    return found


def _security_headers(headers: dict) -> dict:
    important = {
        "content-security-policy": "CSP",
        "strict-transport-security": "HSTS",
        "x-frame-options": "X-Frame-Options",
        "x-content-type-options": "X-Content-Type-Options",
        "referrer-policy": "Referrer-Policy",
        "permissions-policy": "Permissions-Policy",
    }
    present = {}
    missing = []
    for h, label in important.items():
        val = headers.get(h)
        if val:
            present[label] = val
        else:
            missing.append(label)

    score = int(len(present) / len(important) * 100)
    grade = "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "D"
    return {
        "security_score": score,
        "security_grade": grade,
        "present": present,
        "missing": missing,
    }


async def _fetch_page(url: str) -> tuple[httpx.Response, BeautifulSoup, str]:
    try:
        resp = await _client.get(url)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Page returned {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach URL: {e}")
    html = resp.text
    soup = BeautifulSoup(html, "lxml")
    return resp, soup, html


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def root():
    return {"api": "Website SEO & Intelligence API", "version": "1.0.0", "docs": "/docs"}


# ---------------------------------------------------------------------------
# GET /analyze
# ---------------------------------------------------------------------------
@app.get(
    "/analyze",
    summary="Full SEO & intelligence report",
    description=(
        "One-call full analysis: meta tags, OG/Twitter cards, detected tech stack, "
        "HTTP security headers, heading structure, image alt coverage, and link counts."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def analyze(
    url: str = Query(..., description="The full URL to analyse, e.g. https://example.com"),
):
    url = _normalise_url(url)
    key = f"analyze:{url}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    start = time.time()
    resp, soup, html = await _fetch_page(url)
    elapsed = round(time.time() - start, 3)

    headers_dict = dict(resp.headers)
    meta = _extract_meta(soup, html, resp)
    og = _extract_og(soup)
    tech = _detect_tech(html, headers_dict)
    sec = _security_headers(headers_dict)

    # SEO score heuristic
    seo_issues = []
    seo_score = 100
    if not meta["title"]:
        seo_issues.append("Missing <title> tag"); seo_score -= 15
    elif meta["title_length"] < 30:
        seo_issues.append("Title too short (<30 chars)"); seo_score -= 5
    elif meta["title_length"] > 60:
        seo_issues.append("Title too long (>60 chars)"); seo_score -= 5
    if not meta["description"]:
        seo_issues.append("Missing meta description"); seo_score -= 10
    if not meta["canonical_url"]:
        seo_issues.append("No canonical URL set"); seo_score -= 5
    if not meta["h1_tags"]:
        seo_issues.append("No <h1> tag found"); seo_score -= 10
    elif len(meta["h1_tags"]) > 1:
        seo_issues.append("Multiple <h1> tags"); seo_score -= 5
    if meta["images_missing_alt"] > 0:
        seo_issues.append(f"{meta['images_missing_alt']} image(s) missing alt text"); seo_score -= 5
    if not meta["viewport"]:
        seo_issues.append("No viewport meta (not mobile-friendly)"); seo_score -= 10
    seo_score = max(0, seo_score)

    data = {
        "url": str(resp.url),
        "status_code": resp.status_code,
        "fetch_time_seconds": elapsed,
        "content_type": resp.headers.get("content-type"),
        "page_size_bytes": len(resp.content),
        "seo_score": seo_score,
        "seo_issues": seo_issues,
        "meta": meta,
        "social": og,
        "technology": tech,
        "security": sec,
    }
    _cache.set(key, data)
    return success(data)


# ---------------------------------------------------------------------------
# GET /meta
# ---------------------------------------------------------------------------
@app.get(
    "/meta",
    summary="Extract all meta tags",
    description="Returns every <meta> tag on the page, plus title, canonical, and link tags.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_meta(
    url: str = Query(..., description="URL to extract meta from"),
):
    url = _normalise_url(url)
    key = f"meta:{url}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    resp, soup, html = await _fetch_page(url)

    all_meta = []
    for tag in soup.find_all("meta"):
        all_meta.append(dict(tag.attrs))

    all_links = []
    for tag in soup.find_all("link"):
        all_links.append(dict(tag.attrs))

    data = {
        "url": str(resp.url),
        "title": soup.title.get_text(strip=True) if soup.title else None,
        "meta_tags": all_meta,
        "link_tags": all_links,
        "count": len(all_meta),
    }
    _cache.set(key, data)
    return success(data)


# ---------------------------------------------------------------------------
# GET /tech
# ---------------------------------------------------------------------------
@app.get(
    "/tech",
    summary="Technology stack detection",
    description=(
        "Fingerprint the technology stack of any website: CMS, JS framework, "
        "analytics tools, CDN, UI libraries, and more."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def detect_tech(
    url: str = Query(..., description="URL to fingerprint"),
):
    url = _normalise_url(url)
    key = f"tech:{url}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    resp, soup, html = await _fetch_page(url)
    headers_dict = dict(resp.headers)
    tech = _detect_tech(html, headers_dict)

    categories = {
        "cms": [],
        "js_framework": [],
        "analytics": [],
        "cdn_hosting": [],
        "ui_library": [],
        "other": [],
    }
    cms_list = {"WordPress", "Joomla", "Drupal", "Shopify", "Magento", "Wix", "Squarespace", "Webflow"}
    js_list = {"React", "Next.js", "Vue.js", "Angular", "Nuxt.js", "Gatsby", "Svelte"}
    analytics_list = {"Google Analytics", "Google Tag Manager", "Facebook Pixel", "Hotjar", "Intercom", "HubSpot", "Zendesk"}
    cdn_list = {"Cloudflare", "AWS CloudFront", "Fastly", "Vercel", "Netlify"}
    ui_list = {"Bootstrap", "Tailwind CSS", "jQuery", "Font Awesome"}

    for t in tech:
        if t in cms_list:
            categories["cms"].append(t)
        elif t in js_list:
            categories["js_framework"].append(t)
        elif t in analytics_list:
            categories["analytics"].append(t)
        elif t in cdn_list:
            categories["cdn_hosting"].append(t)
        elif t in ui_list:
            categories["ui_library"].append(t)
        else:
            categories["other"].append(t)

    data = {"url": str(resp.url), "technologies_detected": tech, "count": len(tech), "by_category": categories}
    _cache.set(key, data)
    return success(data)


# ---------------------------------------------------------------------------
# GET /social
# ---------------------------------------------------------------------------
@app.get(
    "/social",
    summary="Open Graph and Twitter Card tags",
    description="Extract all Open Graph and Twitter Card meta tags used for social media sharing previews.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_social(
    url: str = Query(..., description="URL to extract social meta from"),
):
    url = _normalise_url(url)
    key = f"social:{url}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    resp, soup, html = await _fetch_page(url)
    og = _extract_og(soup)
    og["url"] = str(resp.url)
    _cache.set(key, og)
    return success(og)


# ---------------------------------------------------------------------------
# GET /headers
# ---------------------------------------------------------------------------
@app.get(
    "/headers",
    summary="HTTP response headers and security analysis",
    description=(
        "Fetch the HTTP response headers for a URL and score them for "
        "security best-practice compliance (CSP, HSTS, X-Frame-Options, etc.)."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_headers(
    url: str = Query(..., description="URL to inspect"),
):
    url = _normalise_url(url)
    key = f"headers:{url}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    try:
        resp = await _client.head(url)
    except Exception:
        try:
            resp = await _client.get(url)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=str(e))

    headers_dict = dict(resp.headers)
    sec = _security_headers(headers_dict)
    data = {
        "url": str(resp.url),
        "status_code": resp.status_code,
        "server": resp.headers.get("server"),
        "content_type": resp.headers.get("content-type"),
        "cache_control": resp.headers.get("cache-control"),
        "all_headers": headers_dict,
        "security_analysis": sec,
    }
    _cache.set(key, data)
    return success(data)


# ---------------------------------------------------------------------------
# GET /sitemap
# ---------------------------------------------------------------------------
@app.get(
    "/sitemap",
    summary="Discover sitemaps for a domain",
    description=(
        "Checks robots.txt for Sitemap: directives and probes common sitemap "
        "paths (/sitemap.xml, /sitemap_index.xml) to return discovered sitemap URLs."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def discover_sitemap(
    domain: str = Query(..., description="Domain name, e.g. example.com"),
):
    domain = domain.strip().lstrip("https://").lstrip("http://").rstrip("/")
    key = f"sitemap:{domain}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    base = f"https://{domain}"
    sitemaps = []

    # 1. Check robots.txt
    try:
        r = await _client.get(f"{base}/robots.txt")
        if r.status_code == 200:
            for line in r.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    sm = line.split(":", 1)[1].strip()
                    sitemaps.append(sm)
    except Exception:
        pass

    # 2. Probe common paths
    common_paths = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml", "/sitemap1.xml"]
    for path in common_paths:
        url = base + path
        if url not in sitemaps:
            try:
                r = await _client.head(url)
                if r.status_code == 200:
                    sitemaps.append(url)
            except Exception:
                pass

    data = {"domain": domain, "sitemaps_found": list(dict.fromkeys(sitemaps)), "count": len(set(sitemaps))}
    _cache.set(key, data, ttl=3600)
    return success(data)
