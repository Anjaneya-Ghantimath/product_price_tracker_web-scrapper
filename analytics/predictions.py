from __future__ import annotations

from typing import List, Tuple

import numpy as np
from sklearn.linear_model import LinearRegression


def simple_price_forecast(prices: List[float], steps_ahead: int = 7) -> List[float]:
    """Predict next prices using linear regression on index vs price."""
    if len(prices) < 2:
        return prices[-1:] * steps_ahead if prices else []
    X = np.arange(len(prices)).reshape(-1, 1)
    y = np.array(prices)
    model = LinearRegression()
    model.fit(X, y)
    future_X = np.arange(len(prices), len(prices) + steps_ahead).reshape(-1, 1)
    preds = model.predict(future_X)
    return [float(max(0.0, p)) for p in preds]


