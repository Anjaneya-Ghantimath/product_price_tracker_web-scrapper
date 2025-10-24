from __future__ import annotations

import os
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
from loguru import logger


def ensure_dirs() -> None:
    for path in [
        "price_tracker/data",
        "price_tracker/logs",
        "price_tracker/static/images",
        "price_tracker/static/css",
    ]:
        os.makedirs(path, exist_ok=True)


def generate_fake_price_history(
    start_price: float, days: int = 30, volatility: float = 0.05
) -> List[Dict[str, float | str | bool]]:
    records: List[Dict[str, float | str | bool]] = []
    price = start_price
    now = datetime.utcnow()
    for i in range(days):
        date = now - timedelta(days=days - i)
        change = random.uniform(-volatility, volatility)
        price = max(0.0, price * (1 + change))
        original = price * (1 + random.uniform(0.05, 0.25))
        discount = round((original - price) / original * 100, 2) if original else None
        records.append(
            {
                "price": round(price, 2),
                "original_price": round(original, 2),
                "discount_percent": discount,
                "availability": True,
                "timestamp": date.isoformat(),
            }
        )
    return records


