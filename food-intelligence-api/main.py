"""
Food Intelligence API
---------------------
Enriched nutrition data, health scoring, allergen detection, and
healthier-alternative suggestions. Powered by Open Food Facts (free, no key).

Endpoints
  GET /product/{barcode}               Full enriched product data
  GET /product/{barcode}/healthscore   Quick health score only
  GET /product/{barcode}/allergens     Allergen report
  GET /product/{barcode}/nutrition     Structured nutrition per serving
  GET /search?q=...                    Search by product name / brand
  GET /compare?barcodes=...            Compare up to 4 products
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional

from common.auth import verify_rapidapi_request
from common.cache import TTLCache
from common.response import success
from enricher import compute_health_score, detect_allergens, compute_daily_values

OFF_BASE = "https://world.openfoodfacts.org"

_cache = TTLCache(maxsize=2000, ttl=3600)
_client: httpx.AsyncClient = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(
        headers={"User-Agent": "FoodIntelligenceAPI/1.0 (contact@yourdomain.com)"},
        timeout=15,
    )
    yield
    await _client.aclose()


app = FastAPI(
    title="Food Intelligence API",
    description="Scan any food barcode and get enriched nutrition data, health scores (0-100), allergen detection, additive warnings, and daily value percentages. Covers 3M+ products worldwide.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


async def _fetch_product(barcode: str) -> dict:
    cached = _cache.get(f"prod:{barcode}")
    if cached:
        return cached
    r = await _client.get(f"{OFF_BASE}/api/v2/product/{barcode}.json")
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    data = r.json()
    if data.get("status") == 0:
        return {}
    product = data.get("product", {})
    _cache.set(f"prod:{barcode}", product)
    return product


def _build_product_response(barcode: str, product: dict) -> dict:
    nutriments = product.get("nutriments", {})
    serving_size_raw = product.get("serving_size") or "100g"
    try:
        serving_g = float("".join(c for c in serving_size_raw if c.isdigit() or c == "."))
    except ValueError:
        serving_g = 100.0

    health = compute_health_score(product)
    daily_values = compute_daily_values(nutriments, serving_g)

    return {
        "barcode": barcode,
        "product_name": product.get("product_name") or product.get("product_name_en"),
        "brand": product.get("brands"),
        "categories": product.get("categories"),
        "image_url": product.get("image_front_url") or product.get("image_url"),
        "quantity": product.get("quantity"),
        "serving_size": serving_size_raw,
        "nutriscore_grade": product.get("nutrition_grades", "").upper() or None,
        "nova_group": product.get("nova_group"),
        "ecoscore_grade": product.get("ecoscore_grade", "").upper() or None,
        "health": {
            "score": health["score"],
            "grade": health["grade"],
            "label": health["label"],
            "flags": health["flags"],
            "reasons": health["reasons"],
        },
        "allergens": {
            "detected": health["allergens_detected"],
            "raw_tags": product.get("allergens_tags", []),
            "traces": product.get("traces_tags", []),
        },
        "additives_of_concern": health["concern_additives"],
        "ingredients": product.get("ingredients_text"),
        "nutrition_per_100g": {
            "energy_kcal": nutriments.get("energy-kcal_100g") or nutriments.get("energy-kcal"),
            "fat_g": nutriments.get("fat_100g") or nutriments.get("fat"),
            "saturated_fat_g": nutriments.get("saturated-fat_100g") or nutriments.get("saturated-fat"),
            "carbohydrates_g": nutriments.get("carbohydrates_100g") or nutriments.get("carbohydrates"),
            "sugars_g": nutriments.get("sugars_100g") or nutriments.get("sugars"),
            "fiber_g": nutriments.get("fiber_100g") or nutriments.get("fiber"),
            "proteins_g": nutriments.get("proteins_100g") or nutriments.get("proteins"),
            "salt_g": nutriments.get("salt_100g") or nutriments.get("salt"),
            "sodium_g": nutriments.get("sodium_100g") or nutriments.get("sodium"),
        },
        "daily_values_per_serving_pct": daily_values,
        "countries": product.get("countries"),
        "labels": product.get("labels"),
    }


@app.get("/", include_in_schema=False)
async def root():
    return {"api": "Food Intelligence API", "version": "1.0.0", "docs": "/docs"}


@app.get(
    "/product/{barcode}",
    summary="Full enriched product data",
    description="Complete product profile including health score, allergens, additives, and nutrition.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_product(barcode: str):
    if not barcode.isdigit():
        raise HTTPException(status_code=400, detail="Barcode must be numeric")
    try:
        product = await _fetch_product(barcode)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {barcode} not found")
    return success(_build_product_response(barcode, product))


@app.get(
    "/product/{barcode}/healthscore",
    summary="Quick health score",
    description="Returns only the 0-100 health score, grade, and flags — fast and lightweight.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_healthscore(barcode: str):
    try:
        product = await _fetch_product(barcode)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {barcode} not found")
    health = compute_health_score(product)
    return success({
        "barcode": barcode,
        "product_name": product.get("product_name"),
        "score": health["score"],
        "grade": health["grade"],
        "label": health["label"],
        "flags": health["flags"],
        "reasons": health["reasons"],
    })


@app.get(
    "/product/{barcode}/allergens",
    summary="Allergen report",
    description="Detailed allergen detection including declared allergens, traces, and ingredient-level scan.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_allergens(barcode: str):
    try:
        product = await _fetch_product(barcode)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {barcode} not found")

    ingredients_text = (product.get("ingredients_text") or "").lower()
    detected = detect_allergens(ingredients_text, product)
    return success({
        "barcode": barcode,
        "product_name": product.get("product_name"),
        "detected_allergens": detected,
        "declared_allergens": product.get("allergens_tags", []),
        "trace_allergens": product.get("traces_tags", []),
        "ingredients_text": product.get("ingredients_text"),
        "total_allergens_found": len(detected),
    })


@app.get(
    "/product/{barcode}/nutrition",
    summary="Structured nutrition per serving",
    description="Nutrition facts with % daily values calculated for the product's serving size.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def get_nutrition(barcode: str):
    try:
        product = await _fetch_product(barcode)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {barcode} not found")

    nutriments = product.get("nutriments", {})
    serving_size_raw = product.get("serving_size") or "100g"
    try:
        serving_g = float("".join(c for c in serving_size_raw if c.isdigit() or c == "."))
    except ValueError:
        serving_g = 100.0

    return success({
        "barcode": barcode,
        "product_name": product.get("product_name"),
        "serving_size": serving_size_raw,
        "serving_size_g": serving_g,
        "per_100g": {
            "energy_kcal": nutriments.get("energy-kcal_100g"),
            "fat_g": nutriments.get("fat_100g"),
            "saturated_fat_g": nutriments.get("saturated-fat_100g"),
            "carbohydrates_g": nutriments.get("carbohydrates_100g"),
            "sugars_g": nutriments.get("sugars_100g"),
            "fiber_g": nutriments.get("fiber_100g"),
            "proteins_g": nutriments.get("proteins_100g"),
            "salt_g": nutriments.get("salt_100g"),
        },
        "per_serving": {
            k: round(v * serving_g / 100, 2) if v is not None else None
            for k, v in {
                "energy_kcal": nutriments.get("energy-kcal_100g"),
                "fat_g": nutriments.get("fat_100g"),
                "saturated_fat_g": nutriments.get("saturated-fat_100g"),
                "carbohydrates_g": nutriments.get("carbohydrates_100g"),
                "sugars_g": nutriments.get("sugars_100g"),
                "fiber_g": nutriments.get("fiber_100g"),
                "proteins_g": nutriments.get("proteins_100g"),
                "salt_g": nutriments.get("salt_100g"),
            }.items()
        },
        "daily_values_per_serving_pct": compute_daily_values(nutriments, serving_g),
    })


@app.get(
    "/search",
    summary="Search products by name or brand",
    description="Full-text search across 3M+ products. Returns health scores with results.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def search_products(
    q: str = Query(..., min_length=2, description="Product name or brand"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
):
    key = f"search:{q.lower()}:{page}:{page_size}"
    cached = _cache.get(key)
    if cached:
        return success(cached)

    try:
        r = await _client.get(
            f"{OFF_BASE}/cgi/search.pl",
            params={
                "search_terms": q,
                "page": page,
                "page_size": page_size,
                "json": 1,
                "fields": "code,product_name,brands,nutrition_grades,nova_group,nutriments,allergens_tags,additives_tags,image_front_url,categories",
            },
        )
        r.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    data = r.json()
    products = data.get("products", [])

    results = []
    for p in products:
        barcode = p.get("code", "")
        if not barcode:
            continue
        health = compute_health_score(p)
        results.append({
            "barcode": barcode,
            "product_name": p.get("product_name"),
            "brand": p.get("brands"),
            "categories": p.get("categories"),
            "image_url": p.get("image_front_url"),
            "nutriscore_grade": (p.get("nutrition_grades") or "").upper() or None,
            "nova_group": p.get("nova_group"),
            "health_score": health["score"],
            "health_grade": health["grade"],
            "allergens_detected": health["allergens_detected"],
        })

    payload = {
        "query": q,
        "page": page,
        "page_size": page_size,
        "total": data.get("count", 0),
        "results": results,
    }
    _cache.set(key, payload, ttl=900)
    return success(payload)


@app.get(
    "/compare",
    summary="Compare multiple products",
    description="Side-by-side comparison of up to 4 products by barcode.",
    dependencies=[Depends(verify_rapidapi_request)],
)
async def compare_products(
    barcodes: str = Query(..., description="Comma-separated barcodes, max 4"),
):
    codes = [b.strip() for b in barcodes.split(",") if b.strip()][:4]
    if len(codes) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 barcodes to compare")

    results = []
    for code in codes:
        try:
            product = await _fetch_product(code)
            if product:
                results.append(_build_product_response(code, product))
            else:
                results.append({"barcode": code, "error": "not found"})
        except Exception:
            results.append({"barcode": code, "error": "fetch failed"})

    # Rank by health score
    ranked = sorted(
        [r for r in results if "health" in r],
        key=lambda x: x["health"]["score"],
        reverse=True,
    )
    if ranked:
        ranked[0]["recommendation"] = "healthiest_option"

    return success({"products": results, "ranked_by_health": [r.get("barcode") for r in ranked]})
