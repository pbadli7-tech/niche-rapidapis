"""
Sentiment analysis using HuggingFace Inference API.
Falls back to keyword-based scoring if HuggingFace is unavailable.
"""
import os
import re
import httpx
from typing import Optional

HF_API_KEY = os.getenv("HUGGINGFACE_API_KEY", "")
HF_MODEL = "cardiffnlp/twitter-roberta-base-sentiment-latest"
HF_URL = f"https://api-inference.huggingface.co/models/{HF_MODEL}"

# Keyword-based fallback
POSITIVE_WORDS = {
    "surge", "rally", "gain", "rise", "grow", "profit", "win", "success",
    "breakthrough", "record", "boost", "soar", "jump", "improve", "strong",
    "positive", "optimism", "recovery", "upbeat", "bullish", "upgrade",
    "outperform", "beat", "exceed", "launch", "approve", "good", "great",
    "excellent", "best", "expand", "increase", "advance", "achieve",
}

NEGATIVE_WORDS = {
    "crash", "drop", "fall", "loss", "decline", "plunge", "slump", "crisis",
    "fail", "debt", "risk", "concern", "worry", "fear", "weak", "bear",
    "cut", "layoff", "downgrade", "miss", "below", "worst", "bad",
    "sell-off", "recession", "inflation", "halt", "ban", "block", "lawsuit",
    "investigation", "fraud", "collapse", "default", "bankrupt", "warning",
}


def keyword_sentiment(text: str) -> dict:
    words = re.findall(r"\b\w+\b", text.lower())
    pos = sum(1 for w in words if w in POSITIVE_WORDS)
    neg = sum(1 for w in words if w in NEGATIVE_WORDS)
    total = pos + neg or 1

    pos_score = pos / total
    neg_score = neg / total
    neu_score = max(0, 1 - pos_score - neg_score)

    if pos > neg:
        label = "positive"
        score = pos_score
    elif neg > pos:
        label = "negative"
        score = neg_score
    else:
        label = "neutral"
        score = 0.5

    return {
        "label": label,
        "score": round(score, 4),
        "positive": round(pos_score, 4),
        "negative": round(neg_score, 4),
        "neutral": round(neu_score, 4),
        "method": "keyword",
    }


async def hf_sentiment(client: httpx.AsyncClient, text: str) -> dict:
    if not HF_API_KEY:
        return keyword_sentiment(text)

    try:
        r = await client.post(
            HF_URL,
            headers={"Authorization": f"Bearer {HF_API_KEY}"},
            json={"inputs": text[:512]},
            timeout=10,
        )
        if r.status_code == 503:
            # Model loading
            return keyword_sentiment(text)
        r.raise_for_status()
        results = r.json()
        if isinstance(results, list) and results:
            scores = results[0] if isinstance(results[0], list) else results
            best = max(scores, key=lambda x: x["score"])
            label_map = {"LABEL_0": "negative", "LABEL_1": "neutral", "LABEL_2": "positive",
                         "negative": "negative", "neutral": "neutral", "positive": "positive"}
            mapped = label_map.get(best["label"], best["label"]).lower()
            pos = next((s["score"] for s in scores if label_map.get(s["label"]) == "positive"), 0)
            neg = next((s["score"] for s in scores if label_map.get(s["label"]) == "negative"), 0)
            neu = next((s["score"] for s in scores if label_map.get(s["label"]) == "neutral"), 0)
            return {
                "label": mapped,
                "score": round(best["score"], 4),
                "positive": round(pos, 4),
                "negative": round(neg, 4),
                "neutral": round(neu, 4),
                "method": "huggingface",
            }
    except Exception:
        pass

    return keyword_sentiment(text)


def aggregate_sentiments(sentiments: list) -> dict:
    if not sentiments:
        return {"label": "neutral", "score": 0.5, "positive": 0.33, "negative": 0.33, "neutral": 0.34}

    avg_pos = sum(s["positive"] for s in sentiments) / len(sentiments)
    avg_neg = sum(s["negative"] for s in sentiments) / len(sentiments)
    avg_neu = sum(s["neutral"] for s in sentiments) / len(sentiments)

    if avg_pos > avg_neg and avg_pos > avg_neu:
        label = "positive"
        score = avg_pos
    elif avg_neg > avg_pos and avg_neg > avg_neu:
        label = "negative"
        score = avg_neg
    else:
        label = "neutral"
        score = avg_neu

    # Sentiment index: -100 (very negative) to +100 (very positive)
    sentiment_index = round((avg_pos - avg_neg) * 100, 1)

    return {
        "label": label,
        "score": round(score, 4),
        "positive": round(avg_pos, 4),
        "negative": round(avg_neg, 4),
        "neutral": round(avg_neu, 4),
        "sentiment_index": sentiment_index,
        "articles_analyzed": len(sentiments),
    }
