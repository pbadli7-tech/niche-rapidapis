"""Health scoring and enrichment layer on top of Open Food Facts data."""
from typing import Optional


ALLERGEN_MAP = {
    "gluten": ["wheat", "barley", "rye", "oat", "spelt", "kamut", "gluten"],
    "dairy": ["milk", "lactose", "casein", "whey", "butter", "cream", "cheese"],
    "nuts": ["peanut", "almond", "cashew", "walnut", "pistachio", "pecan", "hazelnut", "macadamia"],
    "soy": ["soy", "soya", "tofu", "edamame"],
    "eggs": ["egg", "albumin", "mayonnaise"],
    "shellfish": ["shrimp", "prawn", "crab", "lobster", "oyster", "clam", "scallop"],
    "fish": ["fish", "cod", "salmon", "tuna", "anchovy", "sardine", "halibut"],
    "sesame": ["sesame", "tahini"],
    "sulfites": ["sulfite", "sulphite", "sulphur dioxide", "sulfur dioxide"],
}

ADDITIVES_CONCERN = {
    "e102": ("Tartrazine", "high", "Linked to hyperactivity in children"),
    "e110": ("Sunset Yellow", "high", "May cause allergic reactions"),
    "e122": ("Azorubine", "high", "Banned in some countries"),
    "e129": ("Allura Red", "medium", "Possible hyperactivity link"),
    "e211": ("Sodium Benzoate", "medium", "Reacts with Vitamin C to form benzene"),
    "e250": ("Sodium Nitrite", "high", "Potential carcinogen in processed meats"),
    "e621": ("MSG", "low", "Generally recognized as safe by FDA"),
    "e951": ("Aspartame", "medium", "Controversial sweetener"),
    "e954": ("Saccharin", "medium", "Artificial sweetener"),
    "e330": ("Citric Acid", "low", "Generally safe"),
}


def compute_health_score(product: dict) -> dict:
    """Return a 0-100 health score with breakdown."""
    score = 50
    reasons = []
    flags = []

    nutriments = product.get("nutriments", {})
    nutriscore_grade = product.get("nutrition_grades", "").lower()
    nova_group = product.get("nova_group")
    ingredients_text = (product.get("ingredients_text") or "").lower()

    # Nutri-Score (A-E)
    grade_scores = {"a": 30, "b": 20, "c": 0, "d": -15, "e": -25}
    if nutriscore_grade in grade_scores:
        delta = grade_scores[nutriscore_grade]
        score += delta
        reasons.append(f"Nutri-Score {nutriscore_grade.upper()} ({'+' if delta >= 0 else ''}{delta} pts)")

    # NOVA processing level (1-4)
    if nova_group:
        nova = int(nova_group)
        if nova == 1:
            score += 15
            reasons.append("NOVA 1 — unprocessed food (+15 pts)")
        elif nova == 2:
            score += 5
            reasons.append("NOVA 2 — minimally processed (+5 pts)")
        elif nova == 3:
            score -= 10
            reasons.append("NOVA 3 — processed food (-10 pts)")
        elif nova == 4:
            score -= 20
            reasons.append("NOVA 4 — ultra-processed (-20 pts)")
            flags.append({"type": "ultra_processed", "severity": "high", "message": "Ultra-processed food — limit consumption"})

    # Sugar per 100g
    sugar = nutriments.get("sugars_100g") or nutriments.get("sugars")
    if sugar is not None:
        if sugar > 30:
            score -= 15
            reasons.append(f"High sugar: {sugar:.1f}g/100g (-15 pts)")
            flags.append({"type": "high_sugar", "severity": "high", "message": f"{sugar:.1f}g sugar per 100g"})
        elif sugar > 15:
            score -= 7
            reasons.append(f"Moderate sugar: {sugar:.1f}g/100g (-7 pts)")
        elif sugar < 5:
            score += 5
            reasons.append(f"Low sugar: {sugar:.1f}g/100g (+5 pts)")

    # Saturated fat per 100g
    sat_fat = nutriments.get("saturated-fat_100g") or nutriments.get("saturated-fat")
    if sat_fat is not None:
        if sat_fat > 10:
            score -= 10
            reasons.append(f"High saturated fat: {sat_fat:.1f}g/100g (-10 pts)")
            flags.append({"type": "high_sat_fat", "severity": "medium", "message": f"{sat_fat:.1f}g saturated fat per 100g"})
        elif sat_fat > 5:
            score -= 5
            reasons.append(f"Moderate saturated fat: {sat_fat:.1f}g/100g (-5 pts)")

    # Sodium per 100g
    sodium = nutriments.get("sodium_100g") or nutriments.get("sodium")
    if sodium is not None:
        if sodium > 1.5:
            score -= 10
            reasons.append(f"High sodium: {sodium:.2f}g/100g (-10 pts)")
            flags.append({"type": "high_sodium", "severity": "medium", "message": f"{sodium:.2f}g sodium per 100g"})

    # Fiber per 100g (positive)
    fiber = nutriments.get("fiber_100g") or nutriments.get("fiber")
    if fiber is not None and fiber > 3:
        score += 8
        reasons.append(f"Good fiber content: {fiber:.1f}g/100g (+8 pts)")

    # Protein per 100g (positive)
    protein = nutriments.get("proteins_100g") or nutriments.get("proteins")
    if protein is not None and protein > 10:
        score += 5
        reasons.append(f"Good protein: {protein:.1f}g/100g (+5 pts)")

    # Additive check
    additives = product.get("additives_tags", [])
    concern_additives = []
    for tag in additives:
        code = tag.replace("en:", "").lower()
        if code in ADDITIVES_CONCERN:
            name, severity, msg = ADDITIVES_CONCERN[code]
            concern_additives.append({"code": code.upper(), "name": name, "severity": severity, "note": msg})
            if severity == "high":
                score -= 8
            elif severity == "medium":
                score -= 4

    if concern_additives:
        flags.append({"type": "additives_of_concern", "severity": "medium", "additives": concern_additives})

    # Detected allergens
    detected_allergens = detect_allergens(ingredients_text, product)

    score = max(0, min(100, score))

    if score >= 70:
        grade = "A"
        label = "Excellent"
    elif score >= 55:
        grade = "B"
        label = "Good"
    elif score >= 40:
        grade = "C"
        label = "Fair"
    elif score >= 25:
        grade = "D"
        label = "Poor"
    else:
        grade = "E"
        label = "Very Poor"

    return {
        "score": round(score),
        "grade": grade,
        "label": label,
        "reasons": reasons,
        "flags": flags,
        "allergens_detected": detected_allergens,
        "concern_additives": concern_additives,
    }


def detect_allergens(ingredients_text: str, product: dict) -> list:
    detected = []
    allergens_tags = " ".join(product.get("allergens_tags", []) + product.get("traces_tags", []))

    for allergen, keywords in ALLERGEN_MAP.items():
        found = any(kw in ingredients_text or kw in allergens_tags for kw in keywords)
        if found:
            detected.append(allergen)
    return detected


def compute_daily_values(nutriments: dict, serving_size_g: float = 100) -> dict:
    """Return % of recommended daily values per serving."""
    factor = serving_size_g / 100
    dvs = {}

    ref = {
        "energy": 2000,  # kcal
        "fat": 78,       # g
        "saturated-fat": 20,
        "carbohydrates": 275,
        "sugars": 50,
        "fiber": 28,
        "proteins": 50,
        "sodium": 2.3,   # g
        "salt": 6,       # g
    }

    for key, daily_ref in ref.items():
        val = nutriments.get(f"{key}_100g") or nutriments.get(key)
        if val is not None:
            dvs[key] = round((val * factor / daily_ref) * 100, 1)

    return dvs
