from __future__ import annotations

import re
from typing import Any, Dict

from .base_scraper import BaseScraper, bs4


class FlipkartScraper(BaseScraper):
    def supports(self, url: str) -> bool:
        return "flipkart.com" in url

    async def parse(self, html: str, url: str) -> Dict[str, Any]:
        soup = bs4(html)
        title = None
        title_el = soup.select_one("span.B_NuCI") or soup.select_one("h1.yhB1nd")
        if title_el:
            title = title_el.get_text(strip=True)

        price_text = None
        price_el = soup.select_one("div._30jeq3._16Jk6d") or soup.select_one("div.CEmiEU")
        if price_el:
            price_text = price_el.get_text(strip=True)

        orig_text = None
        orig_el = soup.select_one("div._3I9_wc._2p6lqe")
        if orig_el:
            orig_text = orig_el.get_text(strip=True)

        image_url = None
        img_el = soup.select_one("img._396cs4._2amPTt._3qGmMb") or soup.select_one("img.q6DClP")
        if img_el:
            image_url = img_el.get("src")

        availability = True
        oos = soup.find(text=re.compile("out of stock", re.I))
        if oos:
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
            "website": "Flipkart",
        }


