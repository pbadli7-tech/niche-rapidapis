"""
Email Validation & Intelligence API
--------------------------------------
Validate email addresses, check MX records, detect disposable/throwaway
domains, find professional email patterns, and normalise addresses.
No external API key required — uses DNS lookups and built-in logic.

Endpoints
  GET /validate?email=...               Full validation report
  GET /bulk?emails=...                  Validate up to 10 emails at once
  GET /domain?domain=...                MX + deliverability info for a domain
  GET /disposable?email=...             Check if email uses a disposable domain
  GET /normalize?email=...              Normalise (lowercase, Gmail dot-stripping)
  GET /generate?first=...&last=...&domain=...  Common professional email patterns
"""
import os
import re
import sys
import time
import asyncio
import hashlib
from typing import Optional, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dns.resolver
import dns.exception
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from common.auth import verify_rapidapi_request
from common.cache import TTLCache
from common.response import success

_cache = TTLCache(maxsize=2000, ttl=3600)
_executor = ThreadPoolExecutor(max_workers=20)

# ---------------------------------------------------------------------------
# Disposable domain list (top 200 well-known ones — extend as needed)
# ---------------------------------------------------------------------------
DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "guerrillamail.net", "guerrillamail.org",
    "guerrillamail.biz", "guerrillamail.de", "guerrillamail.info",
    "trashmail.com", "trashmail.net", "trashmail.me", "trashmail.at",
    "trashmail.io", "trashmail.xyz",
    "temp-mail.org", "tempmail.com", "tempmail.net", "tempmail.org",
    "throwam.com", "throwam.net", "throwaway.email",
    "yopmail.com", "yopmail.fr", "yopmail.net",
    "sharklasers.com", "guerrillamailblock.com", "grr.la", "spam4.me",
    "10minutemail.com", "10minutemail.net", "10minutemail.org",
    "10minutemail.co.za", "10minutemail.de", "10minutemail.be",
    "minutemailbox.com", "dispostable.com", "mailnull.com", "pookmail.com",
    "spamgourmet.com", "spamgourmet.net", "spamgourmet.org",
    "mailnesia.com", "maildrop.cc", "spamfree24.org", "spamfree.eu",
    "fakeinbox.com", "fakeinbox.net", "fakeinbox.org",
    "throwam.com", "throwam.net", "mytrashmail.com", "mailseal.de",
    "deadaddress.com", "discard.email", "discardmail.com", "discardmail.de",
    "getairmail.com", "getairmail.net", "zetmail.com", "zetmail.net",
    "tempr.email", "dispostable.com", "spamspot.com", "spaml.de",
    "mailexpire.com", "spam.la", "spaml.com", "jetable.com",
    "jetable.net", "jetable.org", "jetable.fr.nf", "nospam.ze.tc",
    "notmailinator.com", "owlpic.com", "fakemailgenerator.com",
    "moakt.com", "mailtemp.net", "tempinbox.com", "emailondeck.com",
    "amilegit.com", "spamgap.com", "mailbucket.org", "gowikibooks.com",
    "gowikicampus.com", "gowikicars.com", "gowikifilms.com", "gowikigames.com",
    "spamgap.com", "spamoff.de", "s0ny.net", "sify.com",
    "binkmail.com", "bio-muesli.net", "dontreg.com", "dontsendmespam.de",
    "einrot.com", "filzmail.com", "fleckens.hu", "gishpuppy.com",
    "gowikimusic.com", "gowikinetwork.com", "gowikitravel.com", "gowikitv.com",
    "humaility.com", "lazyinbox.com", "letthemeatspam.com",
    "lol.ovpn.to", "moncourrier.fr.nf", "monemail.fr.nf",
    "monmail.fr.nf", "msa.minsmail.com", "mt2009.com", "mt2014.com",
    "myspaceinc.com", "myspaceinc.net", "myspaceinc.org", "myspacepimpedup.com",
    "netzidiot.de", "nobulk.com", "noclickemail.com", "nogmailspam.info",
    "nomail.pw", "nomail.xl.cx", "nomail2me.com", "nomorespamemails.com",
    "nospamthanks.info", "nothingtoseehere.ca", "nwldx.com", "obobbo.com",
    "onewaymail.com", "punkass.com", "put2.net", "qisoa.com",
    "quickinbox.com", "recode.me", "recursor.net", "regbypass.com",
    "regbypass.comsafe-mail.net", "rhyta.com", "rklips.com", "rmqkr.net",
    "rppkn.com", "rtrtr.com", "s0ny.net", "safe-mail.net",
    "safetymail.info", "safetypost.de", "sandelf.de", "schafmail.de",
    "sharedmailbox.org", "shortmail.net", "slippery.email", "smellfear.com",
    "snkmail.com", "sofimail.com", "sofort-mail.de", "softbank.ne.jp",
    "sogetthis.com", "soisz.com", "solarino.info", "spam.su",
    "spambox.info", "spambox.irishspringrealty.com", "spambox.us",
    "spamday.com", "spameater.org",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    _executor.shutdown(wait=False)


app = FastAPI(
    title="Email Validation & Intelligence API",
    description=(
        "Validate email addresses with format checking, MX record lookup, "
        "disposable domain detection, and professional pattern generation. "
        "Perfect for lead validation, sign-up forms, and email marketing hygiene."
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def _is_format_valid(email: str) -> bool:
    return bool(EMAIL_RE.match(email))


def _check_mx(domain: str) -> dict:
    """Return MX record info. Blocking — run in executor."""
    key = f"mx:{domain}"
    cached = _cache.get(key)
    if cached:
        return cached
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=5)
        records = sorted(
            [(int(r.preference), str(r.exchange).rstrip(".")) for r in answers],
            key=lambda x: x[0],
        )
        result = {
            "has_mx": True,
            "mx_records": [{"priority": p, "host": h} for p, h in records],
            "primary_mx": records[0][1] if records else None,
        }
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        result = {"has_mx": False, "mx_records": [], "primary_mx": None}
    except dns.exception.Timeout:
        result = {"has_mx": None, "mx_records": [], "primary_mx": None, "note": "DNS timeout"}
    except Exception as e:
        result = {"has_mx": None, "mx_records": [], "primary_mx": None, "note": str(e)}
    _cache.set(key, result, ttl=86400)
    return result


def _normalize_email(email: str) -> str:
    email = email.strip().lower()
    local, _, domain = email.partition("@")
    if domain in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "")
        local = local.split("+")[0]
        domain = "gmail.com"
    elif domain in ("yahoo.com", "yahoo.co.uk"):
        local = local.split("+")[0]
    elif domain in ("outlook.com", "hotmail.com", "live.com"):
        local = local.split("+")[0]
    return f"{local}@{domain}"


def _gravatar_url(email: str) -> str:
    h = hashlib.md5(email.strip().lower().encode()).hexdigest()
    return f"https://www.gravatar.com/avatar/{h}?d=404"


def _role_based(local: str) -> bool:
    role_prefixes = {
        "admin", "info", "contact", "support", "help", "sales", "marketing",
        "billing", "accounts", "hr", "jobs", "careers", "noreply", "no-reply",
        "webmaster", "postmaster", "abuse", "security", "privacy", "legal",
        "press", "media", "newsletter", "team", "hello", "hi", "mail", "office",
    }
    return local.lower().split("+")[0].split(".")[0] in role_prefixes


def _full_validate(email: str) -> dict:
    email = email.strip()
    if not email:
        return {"email": email, "valid": False, "reason": "Empty email address"}

    format_ok = _is_format_valid(email)
    if not format_ok:
        return {
            "email": email,
            "valid": False,
            "format_valid": False,
            "reason": "Invalid email format",
        }

    local, domain = email.rsplit("@", 1)
    is_disposable = domain.lower() in DISPOSABLE_DOMAINS
    mx = _check_mx(domain)
    normalized = _normalize_email(email)
    role = _role_based(local)

    deliverable = mx.get("has_mx") is True and not is_disposable
    score = 0
    if format_ok:
        score += 25
    if mx.get("has_mx"):
        score += 40
    if not is_disposable:
        score += 25
    if not role:
        score += 10
    score = min(score, 100)

    return {
        "email": email,
        "normalized": normalized,
        "valid": format_ok and mx.get("has_mx") is True,
        "deliverable": deliverable,
        "quality_score": score,
        "format_valid": format_ok,
        "mx_found": mx.get("has_mx"),
        "is_disposable": is_disposable,
        "is_role_based": role,
        "domain": domain,
        "mx_records": mx.get("mx_records", []),
        "primary_mx": mx.get("primary_mx"),
        "gravatar_url": _gravatar_url(email),
        "free_provider": domain.lower() in {
            "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
            "icloud.com", "aol.com", "live.com", "protonmail.com",
        },
    }


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def root():
    return {"api": "Email Validation & Intelligence API", "version": "1.0.0", "docs": "/docs"}


# ---------------------------------------------------------------------------
# GET /validate
# ---------------------------------------------------------------------------
@app.get(
    "/validate",
    summary="Validate a single email address",
    description=(
        "Full validation: format check, MX record lookup, disposable domain detection, "
        "role-based address check, quality score (0-100), and normalized form."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def validate_email(
    email: str = Query(..., description="Email address to validate"),
):
    email = email.strip()
    key = f"validate:{email.lower()}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(_executor, _full_validate, email)
    _cache.set(key, data, ttl=3600)
    return success(data)


# ---------------------------------------------------------------------------
# GET /bulk
# ---------------------------------------------------------------------------
@app.get(
    "/bulk",
    summary="Validate up to 10 emails at once",
    description=(
        "Pass a comma-separated list of up to 10 email addresses and get full "
        "validation results for each in a single API call."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def bulk_validate(
    emails: str = Query(..., description="Comma-separated email addresses (max 10)"),
):
    email_list = [e.strip() for e in emails.split(",") if e.strip()][:10]
    if not email_list:
        raise HTTPException(status_code=400, detail="Provide at least one email address")

    key = f"bulk:{','.join(sorted(e.lower() for e in email_list))}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    loop = asyncio.get_event_loop()
    futures = [loop.run_in_executor(_executor, _full_validate, e) for e in email_list]
    results = await asyncio.gather(*futures)

    valid_count = sum(1 for r in results if r.get("valid"))
    data = {
        "total": len(results),
        "valid": valid_count,
        "invalid": len(results) - valid_count,
        "results": list(results),
    }
    _cache.set(key, data, ttl=3600)
    return success(data)


# ---------------------------------------------------------------------------
# GET /domain
# ---------------------------------------------------------------------------
@app.get(
    "/domain",
    summary="Domain email deliverability check",
    description=(
        "Check whether a domain has valid MX records, is a known disposable provider, "
        "and get information about its email infrastructure."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def check_domain(
    domain: str = Query(..., description="Domain name, e.g. example.com"),
):
    domain = domain.strip().lower().lstrip("@")
    key = f"domain:{domain}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    loop = asyncio.get_event_loop()
    mx = await loop.run_in_executor(_executor, _check_mx, domain)

    is_disposable = domain in DISPOSABLE_DOMAINS
    is_free = domain in {
        "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
        "icloud.com", "aol.com", "live.com", "protonmail.com", "zoho.com",
    }

    data = {
        "domain": domain,
        "accepts_email": mx.get("has_mx") is True,
        "mx_found": mx.get("has_mx"),
        "is_disposable": is_disposable,
        "is_free_provider": is_free,
        "mx_records": mx.get("mx_records", []),
        "primary_mx": mx.get("primary_mx"),
        "catch_all": None,  # Would require SMTP probe; not done to avoid being blocked
        "note": "catch_all detection requires SMTP probe and is not performed by default",
    }
    _cache.set(key, data, ttl=86400)
    return success(data)


# ---------------------------------------------------------------------------
# GET /disposable
# ---------------------------------------------------------------------------
@app.get(
    "/disposable",
    summary="Check if an email uses a disposable domain",
    description=(
        "Quick check against a curated list of 100+ known disposable/temporary "
        "email providers (Mailinator, Guerrilla Mail, YOPmail, etc.)."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def check_disposable(
    email: str = Query(..., description="Email address to check"),
):
    email = email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Invalid email address")
    domain = email.rsplit("@", 1)[1]
    is_disposable = domain in DISPOSABLE_DOMAINS
    return success({
        "email": email,
        "domain": domain,
        "is_disposable": is_disposable,
        "verdict": "disposable" if is_disposable else "not_disposable",
    })


# ---------------------------------------------------------------------------
# GET /normalize
# ---------------------------------------------------------------------------
@app.get(
    "/normalize",
    summary="Normalise an email address",
    description=(
        "Returns the canonical form of an email address. "
        "Strips Gmail dots and plus-addressing, lowercases, and handles provider quirks."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def normalize_email(
    email: str = Query(..., description="Email address to normalise"),
):
    email = email.strip()
    if not _is_format_valid(email):
        raise HTTPException(status_code=400, detail="Invalid email format")
    normalized = _normalize_email(email)
    return success({
        "original": email,
        "normalized": normalized,
        "changed": email.lower() != normalized,
    })


# ---------------------------------------------------------------------------
# GET /generate
# ---------------------------------------------------------------------------
@app.get(
    "/generate",
    summary="Generate professional email patterns",
    description=(
        "Given a first name, last name, and company domain, generate the most common "
        "professional email formats used by businesses (e.g. john@acme.com, j.doe@acme.com)."
    ),
    dependencies=[Depends(verify_rapidapi_request)],
)
async def generate_emails(
    first: str = Query(..., description="First name"),
    last: str = Query(..., description="Last name"),
    domain: str = Query(..., description="Company domain, e.g. acme.com"),
):
    f = re.sub(r"[^a-z]", "", first.strip().lower())
    l = re.sub(r"[^a-z]", "", last.strip().lower())
    d = domain.strip().lower().lstrip("@").lstrip("https://").lstrip("http://").rstrip("/")
    if not f or not l or not d:
        raise HTTPException(status_code=400, detail="first, last, and domain are required")

    patterns = [
        f"{f}@{d}",
        f"{f}.{l}@{d}",
        f"{f[0]}{l}@{d}",
        f"{f[0]}.{l}@{d}",
        f"{l}@{d}",
        f"{l}.{f}@{d}",
        f"{l}{f[0]}@{d}",
        f"{f}{l}@{d}",
        f"{f}{l[0]}@{d}",
        f"{f[0]}{l[0]}@{d}",
    ]

    # Check MX once
    loop = asyncio.get_event_loop()
    mx = await loop.run_in_executor(_executor, _check_mx, d)

    return success({
        "first": first.strip(),
        "last": last.strip(),
        "domain": d,
        "domain_accepts_email": mx.get("has_mx"),
        "patterns": patterns,
        "count": len(patterns),
        "note": "Use /validate on each pattern to confirm deliverability",
    })
