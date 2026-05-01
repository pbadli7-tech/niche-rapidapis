"""
Indian Pincode API
------------------
Look up any Indian PIN code to get post offices, districts, states, and
delivery status. Powered by India Post's public data — no scraping.

Endpoints
  GET /pincode/{pincode}           Full info for a 6-digit PIN
  GET /city/{city}                 All PINs in a city / town
  GET /district/{district}         Post offices in a district
  GET /search?q=...                Fuzzy search by name / area
  GET /validate/{pincode}          Quick existence check
  GET /bulk                        Up to 10 pincodes in one call
"""
import os
import sys
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import List

from common.auth import verify_rapidapi_request
from common.cache import TTLCache
from common.response import success, error as err_resp
from fetcher import fetch_by_pincode, fetch_by_city, fetch_by_district

_cache = TTLCache(maxsize=2000, ttl=86400)  # postal data changes rarely
_client: httpx.AsyncClient = None

PIN_RE = re.compile(r"^\d{6}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(timeout=10)
    yield
    await _client.aclose()


app = FastAPI(
    title="Indian Pincode API",
    description="Instant lookup for all 155,000+ Indian PIN codes. Get post office names, districts, states, delivery status, and branch type in a single call.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


@app.get("/", include_in_schema=False)
async def root():
    return {"api": "Indian Pincode API", "version": "1.0.0", "docs": "/docs"}


@app.get(
    "/pincode/{pincode}",
    summary="Look up a PIN code",
    description="Returns all post offices and locality info for a 6-digit Indian PIN code.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def lookup_pincode(pincode: str):
    if not PIN_RE.match(pincode):
        raise HTTPException(status_code=400, detail="PIN code must be exactly 6 digits")

    cached = _cache.get(f"pin:{pincode}")
    if cached:
        return success(cached)

    try:
        result = await fetch_by_pincode(_client, pincode)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream error: {e}")

    if not result["found"]:
        raise HTTPException(status_code=404, detail=f"PIN code {pincode} not found")

    payload = {
        "pincode": pincode,
        "post_offices": result["post_offices"],
        "total_post_offices": len(result["post_offices"]),
        "district": result["post_offices"][0]["district"] if result["post_offices"] else None,
        "state": result["post_offices"][0]["state"] if result["post_offices"] else None,
        "country": "India",
    }
    _cache.set(f"pin:{pincode}", payload)
    return success(payload)


@app.get(
    "/validate/{pincode}",
    summary="Quick PIN code validation",
    description="Returns true/false — fast existence check without full details.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def validate_pincode(pincode: str):
    if not PIN_RE.match(pincode):
        return success({"pincode": pincode, "valid": False, "reason": "must be 6 digits"})
    try:
        result = await fetch_by_pincode(_client, pincode)
        return success({"pincode": pincode, "valid": result["found"]})
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get(
    "/city/{city}",
    summary="All PIN codes for a city or town",
    description="Returns every post office and PIN code for the given city/town name.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def lookup_city(city: str):
    key = f"city:{city.lower()}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    try:
        result = await fetch_by_city(_client, city)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    if not result["found"]:
        raise HTTPException(status_code=404, detail=f"No results for city '{city}'")

    # Group post offices by pincode
    by_pin: dict = {}
    for po in result["post_offices"]:
        pin = po["pincode"]
        by_pin.setdefault(pin, {"pincode": pin, "post_offices": []})
        by_pin[pin]["post_offices"].append(po)

    payload = {
        "city": city,
        "pincodes": list(by_pin.values()),
        "total_pincodes": len(by_pin),
        "total_post_offices": len(result["post_offices"]),
    }
    _cache.set(key, payload)
    return success(payload)


@app.get(
    "/district/{district}",
    summary="All PIN codes in a district",
    description="Returns post offices and PIN codes across a whole district.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def lookup_district(district: str):
    key = f"dist:{district.lower()}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    try:
        pos = await fetch_by_district(_client, district)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    if not pos:
        raise HTTPException(status_code=404, detail=f"No results for district '{district}'")

    unique_pins = sorted(set(p["pincode"] for p in pos))
    payload = {
        "district": district,
        "state": pos[0]["state"] if pos else None,
        "unique_pincodes": unique_pins,
        "total_pincodes": len(unique_pins),
        "post_offices": pos,
    }
    _cache.set(key, payload)
    return success(payload)


@app.get(
    "/bulk",
    summary="Look up multiple PIN codes at once",
    description="Up to 10 PIN codes in a single request. Pass as comma-separated string.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def bulk_lookup(
    pincodes: str = Query(..., description="Comma-separated 6-digit PIN codes, max 10"),
):
    pins = [p.strip() for p in pincodes.split(",") if p.strip()][:10]
    if not pins:
        raise HTTPException(status_code=400, detail="Provide at least one PIN code")

    results = []
    for pin in pins:
        if not PIN_RE.match(pin):
            results.append({"pincode": pin, "error": "invalid format"})
            continue
        cached = _cache.get(f"pin:{pin}")
        if cached:
            results.append({"pincode": pin, "found": True, **cached})
            continue
        try:
            r = await fetch_by_pincode(_client, pin)
            if r["found"] and r["post_offices"]:
                payload = {
                    "pincode": pin,
                    "found": True,
                    "post_offices": r["post_offices"],
                    "district": r["post_offices"][0]["district"],
                    "state": r["post_offices"][0]["state"],
                }
                _cache.set(f"pin:{pin}", payload)
                results.append(payload)
            else:
                results.append({"pincode": pin, "found": False})
        except Exception:
            results.append({"pincode": pin, "error": "upstream error"})

    return success({"results": results, "requested": len(pins), "found": sum(1 for r in results if r.get("found"))})


@app.get(
    "/states",
    summary="List all Indian states",
    description="Returns a static list of all Indian states and union territories.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def list_states():
    states = [
        "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh",
        "Assam", "Bihar", "Chandigarh", "Chhattisgarh",
        "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa", "Gujarat",
        "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand",
        "Karnataka", "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh",
        "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland",
        "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim",
        "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh",
        "Uttarakhand", "West Bengal",
    ]
    return success({"states": states, "count": len(states)})
