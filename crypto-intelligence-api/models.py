from pydantic import BaseModel
from typing import Optional, List


class PricePoint(BaseModel):
    timestamp: int
    price: float
    volume: Optional[float] = None


class TechnicalIndicators(BaseModel):
    rsi_14: Optional[float]
    sma_20: Optional[float]
    sma_50: Optional[float]
    ema_12: Optional[float]
    ema_26: Optional[float]
    macd: Optional[float]
    macd_signal: Optional[float]
    macd_histogram: Optional[float]
    bb_upper: Optional[float]
    bb_middle: Optional[float]
    bb_lower: Optional[float]
    volume_change_24h: Optional[float]


class Signal(BaseModel):
    symbol: str
    name: str
    signal: str          # BUY / SELL / HOLD
    strength: str        # STRONG / MODERATE / WEAK
    confidence: float    # 0-100
    price_usd: float
    price_change_24h: float
    reasoning: List[str]
    indicators: TechnicalIndicators
    generated_at: int


class CoinAnalysis(BaseModel):
    symbol: str
    name: str
    price_usd: float
    market_cap: float
    volume_24h: float
    price_change_24h: float
    price_change_7d: float
    ath: float
    ath_change_percent: float
    indicators: TechnicalIndicators
    signal: Signal
    history_7d: List[PricePoint]


class LeaderboardEntry(BaseModel):
    rank: int
    symbol: str
    name: str
    signal_issued: str
    signal_price: float
    current_price: float
    return_pct: float
    issued_at: int
