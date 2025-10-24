from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, List, Optional

import aiohttp
from loguru import logger

from .amazon_scraper import AmazonScraper
from .base_scraper import BaseScraper
from .flipkart_scraper import FlipkartScraper
from .snapdeal_scraper import SnapdealScraper


def build_scrapers(user_agents: List[str], rate_limit_seconds: float = 2.0) -> List[BaseScraper]:
    return [
        AmazonScraper(user_agents, rate_limit_seconds),
        FlipkartScraper(user_agents, rate_limit_seconds),
        SnapdealScraper(user_agents, rate_limit_seconds),
    ]


async def scrape_multiple_products(
    urls: List[str],
    user_agents: List[str],
    rate_limit_seconds: float = 2.0,
    max_concurrency: int = 8,
    max_attempts: int = 3,
    backoff_base: float = 1.5,
) -> List[Dict[str, Any]]:
    """Scrape multiple products concurrently.

    Handles per-task failures gracefully and returns successful results only.
    """

    scrapers = build_scrapers(user_agents, rate_limit_seconds)

    def pick_scraper(url: str) -> Optional[BaseScraper]:
        for s in scrapers:
            if s.supports(url):
                return s
        return None

    semaphore = asyncio.Semaphore(max_concurrency)

    async def scrape_one(session: aiohttp.ClientSession, url: str) -> Optional[Dict[str, Any]]:
        scraper = pick_scraper(url)
        if not scraper:
            logger.warning(f"No scraper supports URL: {url}")
            return None
        try:
            async with semaphore:
                html = await scraper.fetch(session, url, max_attempts=max_attempts, backoff_base=backoff_base)
                data = await scraper.parse(html, url)
                return data
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Failed to scrape {url}: {exc}")
            return None

    timeout = aiohttp.ClientTimeout(total=30)
    connector = aiohttp.TCPConnector(limit_per_host=max_concurrency)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        results = await asyncio.gather(*(scrape_one(session, u) for u in urls))
    return [r for r in results if r]


