from __future__ import annotations

import asyncio
import ssl
from typing import Any, Dict, Iterable, List, Optional

import aiohttp
from loguru import logger

from .amazon_scraper import AmazonScraper
from .base_scraper import BaseScraper
from .flipkart_scraper import FlipkartScraper
from .snapdeal_scraper import SnapdealScraper
from .meesho_scraper import MeeshoScraper
from .myntra_scraper import MyntraScraper
from .nykaa_scraper import NykaaScraper
from .ajio_scraper import AjioScraper
from .jiomart_scraper import JioMartScraper
from .fallback_scraper import FallbackScraper


def build_scrapers(user_agents: List[str], rate_limit_seconds: float = 2.0) -> List[BaseScraper]:
    return [
        AmazonScraper(user_agents, rate_limit_seconds),
        FlipkartScraper(user_agents, rate_limit_seconds),
        SnapdealScraper(user_agents, rate_limit_seconds),
        MeeshoScraper(user_agents, rate_limit_seconds),
        MyntraScraper(user_agents, rate_limit_seconds),
        NykaaScraper(user_agents, rate_limit_seconds),
        AjioScraper(user_agents, rate_limit_seconds),
        JioMartScraper(user_agents, rate_limit_seconds),
        FallbackScraper(user_agents, rate_limit_seconds),  # Fallback for any website
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
                logger.info(f"Scraping {url} with {scraper.__class__.__name__}")
                html = await scraper.fetch(session, url, max_attempts=max_attempts, backoff_base=backoff_base)
                
                if not html:
                    logger.warning(f"No HTML content received for {url}")
                    return None
                
                data = await scraper.parse(html, url)
                
                # Validate scraped data
                if not data or not data.get('title'):
                    logger.warning(f"No valid data scraped from {url}")
                    return None
                
                logger.info(f"Successfully scraped {url}: {data.get('title', 'No title')}")
                return data
                
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Failed to scrape {url}: {exc}")
            # Try fallback scraper if specific scraper failed
            try:
                fallback_scraper = FallbackScraper(user_agents, rate_limit_seconds)
                logger.info(f"Trying fallback scraper for {url}")
                html = await fallback_scraper.fetch(session, url, max_attempts=max_attempts, backoff_base=backoff_base)
                if html:
                    data = await fallback_scraper.parse(html, url)
                    if data and data.get('title'):
                        logger.info(f"Fallback scraper succeeded for {url}")
                        return data
            except Exception as fallback_exc:  # noqa: BLE001
                logger.error(f"Fallback scraper also failed for {url}: {fallback_exc}")
            
            return None

    # Create SSL context that can handle certificate issues
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    timeout = aiohttp.ClientTimeout(total=30)
    connector = aiohttp.TCPConnector(limit_per_host=max_concurrency, ssl=ssl_context)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        results = await asyncio.gather(*(scrape_one(session, u) for u in urls))
    return [r for r in results if r]


