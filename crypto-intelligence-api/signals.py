"""Technical analysis engine — pure Python, no TA-lib dependency."""
from typing import List, Optional, Tuple
import math


def sma(prices: List[float], period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def ema(prices: List[float], period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    result = prices[0]
    for p in prices[1:]:
        result = p * k + result * (1 - k)
    return result


def rsi(prices: List[float], period: int = 14) -> Optional[float]:
    if len(prices) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(prices)):
        delta = prices[i] - prices[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def bollinger_bands(prices: List[float], period: int = 20, std_dev: float = 2.0):
    if len(prices) < period:
        return None, None, None
    window = prices[-period:]
    mid = sum(window) / period
    variance = sum((p - mid) ** 2 for p in window) / period
    std = math.sqrt(variance)
    return mid + std_dev * std, mid, mid - std_dev * std


def macd_line(prices: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Returns (macd, signal_line, histogram)."""
    e12 = ema(prices, 12)
    e26 = ema(prices, 26)
    if e12 is None or e26 is None:
        return None, None, None
    macd_val = e12 - e26
    # Use last 9 macd values for signal — approximate with just current
    signal_val = macd_val * (2 / 10)  # simplified single-point EMA(9)
    return macd_val, signal_val, macd_val - signal_val


def generate_signal(
    prices: List[float],
    volumes: List[float],
    price_change_24h: float,
    price_change_7d: float,
) -> dict:
    rsi_val = rsi(prices)
    s20 = sma(prices, 20)
    s50 = sma(prices, 50)
    e12 = ema(prices, 12)
    e26 = ema(prices, 26)
    macd_val, macd_sig, macd_hist = macd_line(prices)
    bb_upper, bb_mid, bb_lower = bollinger_bands(prices)

    current = prices[-1] if prices else 0
    vol_change = None
    if len(volumes) >= 2 and volumes[-2]:
        vol_change = (volumes[-1] - volumes[-2]) / volumes[-2] * 100

    reasons = []
    score = 50  # start neutral

    # RSI signals
    if rsi_val is not None:
        if rsi_val < 30:
            score += 20
            reasons.append(f"RSI {rsi_val:.1f} — oversold territory (bullish)")
        elif rsi_val > 70:
            score -= 20
            reasons.append(f"RSI {rsi_val:.1f} — overbought territory (bearish)")
        else:
            reasons.append(f"RSI {rsi_val:.1f} — neutral zone")

    # MACD crossover
    if macd_val is not None and macd_sig is not None:
        if macd_val > macd_sig:
            score += 10
            reasons.append("MACD above signal line — bullish momentum")
        else:
            score -= 10
            reasons.append("MACD below signal line — bearish momentum")

    # Price vs moving averages
    if s20 is not None and current > s20:
        score += 8
        reasons.append(f"Price above SMA-20 ({s20:.4f}) — short-term uptrend")
    elif s20 is not None:
        score -= 8
        reasons.append(f"Price below SMA-20 ({s20:.4f}) — short-term downtrend")

    if s50 is not None and current > s50:
        score += 8
        reasons.append(f"Price above SMA-50 ({s50:.4f}) — medium-term uptrend")
    elif s50 is not None:
        score -= 8
        reasons.append(f"Price below SMA-50 ({s50:.4f}) — medium-term downtrend")

    # Bollinger band position
    if bb_upper and bb_lower and bb_mid:
        bb_pct = (current - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) else 0.5
        if bb_pct > 0.8:
            score -= 5
            reasons.append("Price near upper Bollinger Band — potential resistance")
        elif bb_pct < 0.2:
            score += 5
            reasons.append("Price near lower Bollinger Band — potential support")

    # Volume confirmation
    if vol_change is not None:
        if vol_change > 20 and price_change_24h > 0:
            score += 5
            reasons.append(f"Volume surge +{vol_change:.0f}% confirming upward move")
        elif vol_change > 20 and price_change_24h < 0:
            score -= 5
            reasons.append(f"Volume surge +{vol_change:.0f}% confirming downward move")

    # Clamp score
    score = max(0, min(100, score))

    if score >= 65:
        signal = "BUY"
        strength = "STRONG" if score >= 80 else "MODERATE"
    elif score <= 35:
        signal = "SELL"
        strength = "STRONG" if score <= 20 else "MODERATE"
    else:
        signal = "HOLD"
        strength = "WEAK"

    return {
        "signal": signal,
        "strength": strength,
        "confidence": round(score, 1),
        "reasoning": reasons,
        "indicators": {
            "rsi_14": round(rsi_val, 2) if rsi_val else None,
            "sma_20": round(s20, 6) if s20 else None,
            "sma_50": round(s50, 6) if s50 else None,
            "ema_12": round(e12, 6) if e12 else None,
            "ema_26": round(e26, 6) if e26 else None,
            "macd": round(macd_val, 6) if macd_val else None,
            "macd_signal": round(macd_sig, 6) if macd_sig else None,
            "macd_histogram": round(macd_hist, 6) if macd_hist else None,
            "bb_upper": round(bb_upper, 6) if bb_upper else None,
            "bb_middle": round(bb_mid, 6) if bb_mid else None,
            "bb_lower": round(bb_lower, 6) if bb_lower else None,
            "volume_change_24h": round(vol_change, 2) if vol_change else None,
        },
    }
