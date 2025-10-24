"""SQLite database manager with connection pooling and CRUD operations.

Implements context managers, parameterized queries, and data validation.
"""

from __future__ import annotations

import os
import queue
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple

from loguru import logger

from .models import (
    ALERTS_SCHEMA_SQL,
    PRICE_HISTORY_SCHEMA_SQL,
    PRODUCTS_SCHEMA_SQL,
)


class SQLiteConnectionPool:
    """Simple thread-safe SQLite connection pool.

    Note: SQLite connections must be used in the same thread by default.
    We set check_same_thread=False and guard access via a queue.
    """

    def __init__(self, db_path: str, pool_size: int = 5) -> None:
        self.db_path = db_path
        self.pool_size = max(1, pool_size)
        self._pool: "queue.Queue[sqlite3.Connection]" = queue.Queue()
        self._lock = threading.Lock()
        for _ in range(self.pool_size):
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._pool.put(conn)

    def get(self) -> sqlite3.Connection:
        return self._pool.get()

    def put(self, conn: sqlite3.Connection) -> None:
        self._pool.put(conn)

    def closeall(self) -> None:
        while not self._pool.empty():
            conn = self._pool.get_nowait()
            conn.close()


class DatabaseManager:
    """High-level database operations for the Price Tracker app."""

    def __init__(self, db_path: str, pool_size: int = 5) -> None:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.pool = SQLiteConnectionPool(db_path, pool_size)
        self._initialize()

    def _initialize(self) -> None:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(PRODUCTS_SCHEMA_SQL)
            cur.execute(PRICE_HISTORY_SCHEMA_SQL)
            cur.execute(ALERTS_SCHEMA_SQL)
            conn.commit()

    @contextmanager
    def get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self.pool.get()
        try:
            yield conn
        finally:
            self.pool.put(conn)

    # CRUD operations
    def add_product(
        self,
        url: str,
        name: Optional[str],
        website: Optional[str],
        category: Optional[str],
        image_path: Optional[str],
        user_threshold: Optional[float],
        check_frequency: Optional[int],
        is_active: bool = True,
    ) -> int:
        now = datetime.utcnow().isoformat()
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT OR IGNORE INTO products
                (url, name, website, category, image_path, date_added, last_checked, is_active, user_threshold, check_frequency)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    url,
                    name,
                    website,
                    category,
                    image_path,
                    now,
                    None,
                    1 if is_active else 0,
                    user_threshold,
                    check_frequency,
                ),
            )
            conn.commit()
            return cur.lastrowid or self.get_product_id_by_url(url)

    def get_product_id_by_url(self, url: str) -> Optional[int]:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM products WHERE url=?", (url,))
            row = cur.fetchone()
            return int(row[0]) if row else None

    def list_products(self, only_active: bool = True) -> List[sqlite3.Row]:
        with self.get_conn() as conn:
            cur = conn.cursor()
            if only_active:
                cur.execute("SELECT * FROM products WHERE is_active=1 ORDER BY date_added DESC")
            else:
                cur.execute("SELECT * FROM products ORDER BY date_added DESC")
            return cur.fetchall()

    def update_product(self, product_id: int, fields: Dict[str, Any]) -> None:
        if not fields:
            return
        keys = ", ".join([f"{k}=?" for k in fields.keys()])
        values = list(fields.values()) + [product_id]
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(f"UPDATE products SET {keys} WHERE id=?", values)
            conn.commit()

    def archive_inactive_older_than(self, days: int = 30) -> int:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE products SET is_active=0 WHERE last_checked IS NOT NULL AND last_checked < ?",
                (cutoff,),
            )
            conn.commit()
            return cur.rowcount

    def add_price_history(
        self,
        product_id: int,
        price: Optional[float],
        original_price: Optional[float],
        discount_percent: Optional[float],
        availability: Optional[bool],
        timestamp: Optional[str] = None,
    ) -> int:
        ts = timestamp or datetime.utcnow().isoformat()
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO price_history (product_id, price, original_price, discount_percent, availability, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (product_id, price, original_price, discount_percent, 1 if availability else 0, ts),
            )
            conn.commit()
            return cur.lastrowid

    def latest_price(self, product_id: int) -> Optional[sqlite3.Row]:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM price_history WHERE product_id=?
                ORDER BY timestamp DESC LIMIT 1
                """,
                (product_id,),
            )
            return cur.fetchone()

    def list_price_history(self, product_id: int, limit: Optional[int] = None) -> List[sqlite3.Row]:
        with self.get_conn() as conn:
            cur = conn.cursor()
            query = "SELECT * FROM price_history WHERE product_id=? ORDER BY timestamp DESC"
            if limit:
                query += f" LIMIT {int(limit)}"
            cur.execute(query, (product_id,))
            return cur.fetchall()

    def add_alert(
        self,
        product_id: int,
        alert_type: str,
        message: str,
        price_at_alert: Optional[float],
        timestamp: Optional[str] = None,
        is_read: bool = False,
    ) -> int:
        ts = timestamp or datetime.utcnow().isoformat()
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO alerts (product_id, alert_type, message, price_at_alert, timestamp, is_read)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (product_id, alert_type, message, price_at_alert, ts, 1 if is_read else 0),
            )
            conn.commit()
            return cur.lastrowid

    def list_alerts(self, only_unread: bool = False) -> List[sqlite3.Row]:
        with self.get_conn() as conn:
            cur = conn.cursor()
            if only_unread:
                cur.execute("SELECT * FROM alerts WHERE is_read=0 ORDER BY timestamp DESC")
            else:
                cur.execute("SELECT * FROM alerts ORDER BY timestamp DESC")
            return cur.fetchall()

    def mark_alert_read(self, alert_id: int) -> None:
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE alerts SET is_read=1 WHERE id=?", (alert_id,))
            conn.commit()

    # Maintenance
    def cleanup_old_price_history(self, days: int = 365) -> int:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM price_history WHERE timestamp < ?", (cutoff,))
            conn.commit()
            return cur.rowcount


