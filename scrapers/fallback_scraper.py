from __future__ import annotations

import re
from typing import Any, Dict

from .base_scraper import BaseScraper, bs4


class FallbackScraper(BaseScraper):
    def supports(self, url: str) -> bool:
        return True  # This scraper supports all URLs as fallback

    async def parse(self, html: str, url: str) -> Dict[str, Any]:
        soup = bs4(html)
        
        # Generic product title selectors
        title_el = soup.select_one("h1") or \
                  soup.select_one("h2") or \
                  soup.select_one("[class*='title']") or \
                  soup.select_one("[class*='name']") or \
                  soup.select_one("title")
        title = title_el.get_text(strip=True) if title_el else None

        # Generic price selectors
        price_el = soup.select_one("[class*='price']") or \
                  soup.select_one("[class*='cost']") or \
                  soup.select_one("[class*='amount']") or \
                  soup.select_one("span") or \
                  soup.select_one("div")
        
        # Look for price patterns in text
        price_text = None
        if price_el:
            price_text = price_el.get_text(strip=True)
        
        # If no price found, search for price patterns in all text
        if not price_text:
            price_patterns = [
                r'₹\s*[\d,]+',
                r'Rs\.?\s*[\d,]+',
                r'INR\s*[\d,]+',
                r'\$\s*[\d,]+',
                r'[\d,]+\.?\d*\s*(?:₹|Rs|INR|\$)'
            ]
            
            for pattern in price_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                if matches:
                    price_text = matches[0]
                    break

        # Generic original price selectors
        orig_el = soup.select_one("[class*='original']") or \
                 soup.select_one("[class*='mrp']") or \
                 soup.select_one("[class*='strike']") or \
                 soup.select_one("s") or \
                 soup.select_one("del")
        orig_text = orig_el.get_text(strip=True) if orig_el else None

        # Generic image selectors
        img_el = soup.select_one("img[alt*='product']") or \
                soup.select_one("img[src*='product']") or \
                soup.select_one("img[class*='product']") or \
                soup.select_one("img") or \
                soup.select_one("picture img")
        image_url = img_el.get("src") or img_el.get("data-src") if img_el else None

        # Availability - look for out of stock indicators
        availability = True
        out_of_stock_indicators = [
            "out of stock", "sold out", "unavailable", "not available", 
            "currently unavailable", "temporarily unavailable"
        ]
        for indicator in out_of_stock_indicators:
            if soup.find(text=re.compile(indicator, re.I)):
                availability = False
                break

        def parse_price(text: str | None) -> float | None:
            if not text:
                return None
            # Extract numbers from price text
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

        # Determine website from URL
        website = "Unknown"
        if "amazon." in url:
            website = "Amazon"
        elif "flipkart.com" in url:
            website = "Flipkart"
        elif "snapdeal.com" in url:
            website = "Snapdeal"
        elif "meesho.com" in url:
            website = "Meesho"
        elif "myntra.com" in url:
            website = "Myntra"
        elif "nykaa.com" in url:
            website = "Nykaa"
        elif "ajio.com" in url:
            website = "Ajio"
        elif "jiomart.com" in url:
            website = "JioMart"

        return {
            "url": url,
            "title": title,
            "current_price": price,
            "original_price": original_price,
            "discount_percent": discount_percent,
            "image_url": image_url,
            "availability": availability,
            "website": website,
        }
