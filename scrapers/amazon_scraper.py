from __future__ import annotations

import re
from typing import Any, Dict

from .base_scraper import BaseScraper, bs4


class AmazonScraper(BaseScraper):
    def supports(self, url: str) -> bool:
        return "amazon." in url

    async def parse(self, html: str, url: str) -> Dict[str, Any]:
        soup = bs4(html)
        title = None
        title_el = soup.select_one("#productTitle") or soup.select_one("span#title")
        if title_el:
            title = title_el.get_text(strip=True)

        price_text = None
        for sel in [
            "#priceblock_dealprice",
            "#priceblock_ourprice",
            "span.a-price > span.a-offscreen",
            "span.a-price-whole",
        ]:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                price_text = el.get_text(strip=True)
                break

        orig_text = None
        strike = soup.select_one("span.priceBlockStrikePriceString, span.a-text-price > span.a-offscreen")
        if strike:
            orig_text = strike.get_text(strip=True)

        image_url = None
        img_el = soup.select_one("#landingImage, #imgTagWrapperId img, img#imgBlkFront")
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-old-hires")

        availability_text = (soup.select_one("#availability span") or soup.select_one("div#availability span")).get_text(strip=True) if soup.select_one("#availability span") or soup.select_one("div#availability span") else ""
        availability = "in stock" in availability_text.lower() or "available" in availability_text.lower()

        def parse_price(text: str | None) -> float | None:
            if not text:
                return None
            cleaned = re.sub(r"[^0-9.,]", "", text).replace(",", "")
            try:
                return float(cleaned)
            except Exception:  # noqa: BLE001
                return None

        price = parse_price(price_text)
        original_price = parse_price(orig_text)
        discount_percent = None
        if price and original_price and original_price > 0:
            discount_percent = round((original_price - price) / original_price * 100, 2)

        return {
            "url": url,
            "title": title,
            "current_price": price,
            "original_price": original_price,
            "discount_percent": discount_percent,
            "image_url": image_url,
            "availability": availability,
            "website": "Amazon",
        }


