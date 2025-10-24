from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd


@dataclass
class DealScoreWeights:
    vs_avg: float = 0.4
    vs_low: float = 0.3
    discount: float = 0.2
    stock: float = 0.1


def compute_deal_score(history_df: pd.DataFrame, current_price: Optional[float], discount_percent: Optional[float], availability: bool) -> int:
    if history_df.empty or current_price is None:
        return 0
    avg_price = float(history_df["price"].mean())
    low_price = float(history_df["price"].min())
    w = DealScoreWeights()
    score = 0.0
    if avg_price > 0:
        score += max(0.0, min(1.0, (avg_price - current_price) / avg_price)) * w.vs_avg
    if low_price > 0:
        score += max(0.0, min(1.0, (current_price - low_price) / low_price)) * w.vs_low
    if discount_percent is not None:
        score += max(0.0, min(1.0, discount_percent / 100.0)) * w.discount
    if availability:
        score += w.stock
    return int(round(score * 100))


def volatility_indicator(history_df: pd.DataFrame) -> float:
    if len(history_df) < 2:
        return 0.0
    return float(history_df["price"].pct_change().abs().mean())


