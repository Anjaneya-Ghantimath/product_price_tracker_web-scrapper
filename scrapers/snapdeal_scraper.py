from __future__ import annotations

import re
from typing import Any, Dict

from .base_scraper import BaseScraper, bs4


class SnapdealScraper(BaseScraper):
    def supports(self, url: str) -> bool:
        return "snapdeal.com" in url

    async def parse(self, html: str, url: str) -> Dict[str, Any]:
        soup = bs4(html)
        title_el = soup.select_one("h1.pdp-e-i-head") or soup.select_one("h1#productTitle")
        title = title_el.get_text(strip=True) if title_el else None

        price_el = soup.select_one("span.pdp-final-price") or soup.select_one("span#selling-price-id")
        price_text = price_el.get_text(strip=True) if price_el else None

        orig_el = soup.select_one("span.pdpCutPrice") or soup.select_one("span#original-price-id")
        orig_text = orig_el.get_text(strip=True) if orig_el else None

        img_el = soup.select_one("img.cloudzoom") or soup.select_one("img#bx-slider-left-image-panel")
        image_url = img_el.get("src") if img_el else None

        availability = True
        if soup.find(text=re.compile("sold out|out of stock", re.I)):
            availability = False

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
            "website": "Snapdeal",
        }


