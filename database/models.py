"""Database schema definitions and helpers for SQLite.

This module defines table creation SQL and simple dataclasses for type hints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


PRODUCTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    name TEXT,
    website TEXT,
    category TEXT,
    image_path TEXT,
    date_added TIMESTAMP,
    last_checked TIMESTAMP,
    is_active BOOLEAN,
    user_threshold REAL,
    check_frequency INTEGER
);
"""


PRICE_HISTORY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY,
    product_id INTEGER,
    price REAL,
    original_price REAL,
    discount_percent REAL,
    availability BOOLEAN,
    timestamp TIMESTAMP,
    FOREIGN KEY(product_id) REFERENCES products(id)
);
"""


ALERTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    product_id INTEGER,
    alert_type TEXT,
    message TEXT,
    price_at_alert REAL,
    timestamp TIMESTAMP,
    is_read BOOLEAN,
    FOREIGN KEY(product_id) REFERENCES products(id)
);
"""


@dataclass
class Product:
    id: Optional[int]
    url: str
    name: Optional[str]
    website: Optional[str]
    category: Optional[str]
    image_path: Optional[str]
    date_added: Optional[str]
    last_checked: Optional[str]
    is_active: bool
    user_threshold: Optional[float]
    check_frequency: Optional[int]


@dataclass
class PriceHistory:
    id: Optional[int]
    product_id: int
    price: Optional[float]
    original_price: Optional[float]
    discount_percent: Optional[float]
    availability: Optional[bool]
    timestamp: Optional[str]


@dataclass
class Alert:
    id: Optional[int]
    product_id: int
    alert_type: str
    message: str
    price_at_alert: Optional[float]
    timestamp: Optional[str]
    is_read: bool


