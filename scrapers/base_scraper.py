"""Abstract base scraper and utilities."""

from __future__ import annotations

import asyncio
import random
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import aiohttp
from bs4 import BeautifulSoup
from loguru import logger


class RateLimiter:
    """Simple rate limiter to sleep between requests per host."""

    def __init__(self, min_interval_seconds: float = 2.0) -> None:
        self.min_interval_seconds = min_interval_seconds
        self._last_ts: float = 0.0

    async def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_ts
        if elapsed < self.min_interval_seconds:
            await asyncio.sleep(self.min_interval_seconds - elapsed)
        self._last_ts = time.monotonic()


class BaseScraper(ABC):
    """Common interface for site scrapers."""

    def __init__(self, user_agents: List[str], rate_limit_seconds: float = 2.0) -> None:
        self.user_agents = user_agents
        self.ratelimiter = RateLimiter(rate_limit_seconds)

    @abstractmethod
    def supports(self, url: str) -> bool:
        ...

    @abstractmethod
    async def parse(self, html: str, url: str) -> Dict[str, Any]:
        ...

    async def fetch(self, session: aiohttp.ClientSession, url: str, max_attempts: int = 3, backoff_base: float = 1.5) -> str:
        attempt = 0
        while True:
            await self.ratelimiter.wait()
            headers = {"User-Agent": random.choice(self.user_agents)}
            try:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status == 200:
                        return await resp.text()
                    if resp.status in (403, 429, 503):
                        raise aiohttp.ClientResponseError(request_info=resp.request_info, history=(), status=resp.status)
                    logger.warning(f"Non-200 status {resp.status} for {url}")
                    return await resp.text()
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                if attempt >= max_attempts:
                    logger.error(f"Fetch failed for {url}: {exc}")
                    raise
                sleep_for = backoff_base ** attempt + random.uniform(0, 0.5)
                logger.info(f"Retrying {url} in {sleep_for:.2f}s (attempt {attempt})")
                await asyncio.sleep(sleep_for)

    async def scrape(self, session: aiohttp.ClientSession, url: str) -> Dict[str, Any]:
        html = await self.fetch(session, url)
        return await self.parse(html, url)


def bs4(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


