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

EMAIL_SUBSCRIBERS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS email_subscribers (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    preferences TEXT DEFAULT '{}'
);
"""

ALERT_SCHEDULES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS alert_schedules (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    frequency_hours INTEGER DEFAULT 24,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

GMAIL_ACCOUNTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS gmail_accounts (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    app_password TEXT NOT NULL,
    name TEXT,
    is_active BOOLEAN DEFAULT 1,
    is_default BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used TIMESTAMP
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


@dataclass
class EmailSubscriber:
    id: Optional[int]
    email: str
    name: Optional[str]
    is_active: bool
    created_at: Optional[str]
    preferences: str


@dataclass
class AlertSchedule:
    id: Optional[int]
    name: str
    frequency_hours: int
    is_active: bool
    created_at: Optional[str]


@dataclass
class GmailAccount:
    id: Optional[int]
    email: str
    app_password: str
    name: Optional[str]
    is_active: bool
    is_default: bool
    created_at: Optional[str]
    last_used: Optional[str]


