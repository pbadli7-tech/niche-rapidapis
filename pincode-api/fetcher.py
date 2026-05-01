"""Fetches pincode data from India Post's free public API."""
import httpx
from typing import Optional

INDIA_POST_API = "https://api.postalpincode.in"


async def fetch_by_pincode(client: httpx.AsyncClient, pincode: str) -> dict:
    r = await client.get(f"{INDIA_POST_API}/pincode/{pincode}")
    r.raise_for_status()
    data = r.json()
    if not data or data[0].get("Status") == "Error":
        return {"found": False, "message": data[0].get("Message", "Not found"), "post_offices": []}
    return {
        "found": True,
        "message": data[0].get("Message", ""),
        "post_offices": _normalize_pos(data[0].get("PostOffice") or []),
    }


async def fetch_by_city(client: httpx.AsyncClient, city: str) -> dict:
    r = await client.get(f"{INDIA_POST_API}/postoffice/{city.lower()}")
    r.raise_for_status()
    data = r.json()
    if not data or data[0].get("Status") == "Error":
        return {"found": False, "message": "No results", "post_offices": []}
    return {
        "found": True,
        "message": data[0].get("Message", ""),
        "post_offices": _normalize_pos(data[0].get("PostOffice") or []),
    }


async def fetch_by_district(client: httpx.AsyncClient, district: str) -> list:
    """India Post API doesn't have direct district lookup; aggregate from city search."""
    r = await client.get(f"{INDIA_POST_API}/postoffice/{district.lower()}")
    r.raise_for_status()
    data = r.json()
    if not data or data[0].get("Status") == "Error":
        return []
    pos = _normalize_pos(data[0].get("PostOffice") or [])
    # Filter to those matching the district
    return [p for p in pos if p["district"].lower() == district.lower()] or pos


def _normalize_pos(raw: list) -> list:
    return [
        {
            "name": p.get("Name", ""),
            "branch_type": p.get("BranchType"),
            "delivery_status": p.get("DeliveryStatus"),
            "circle": p.get("Circle"),
            "district": p.get("District", ""),
            "division": p.get("Division"),
            "region": p.get("Region"),
            "state": p.get("State", ""),
            "country": p.get("Country", "India"),
            "pincode": p.get("Pincode", ""),
        }
        for p in raw
    ]
