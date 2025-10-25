from __future__ import annotations

import re
from typing import Any, Dict

from .base_scraper import BaseScraper, bs4


class AjioScraper(BaseScraper):
    def supports(self, url: str) -> bool:
        return "ajio.com" in url

    async def parse(self, html: str, url: str) -> Dict[str, Any]:
        soup = bs4(html)
        
        # Product title
        title_el = soup.select_one("h1[data-testid='product-title']") or soup.select_one(".product-title") or soup.select_one("h1")
        title = title_el.get_text(strip=True) if title_el else None

        # Current price - Ajio specific selectors
        price_el = soup.select_one("[data-testid='product-price']") or \
                  soup.select_one(".product-price") or \
                  soup.select_one(".price") or \
                  soup.select_one("[class*='price']") or \
                  soup.select_one(".selling-price") or \
                  soup.select_one(".pdp-price") or \
                  soup.select_one(".final-price")
        price_text = price_el.get_text(strip=True) if price_el else None
        
        # If no price found with selectors, try to find price patterns in text
        if not price_text:
            price_patterns = [
                r'₹\s*[\d,]+',
                r'Rs\.?\s*[\d,]+',
                r'INR\s*[\d,]+',
                r'[\d,]+\.?\d*\s*(?:₹|Rs|INR)'
            ]
            
            for pattern in price_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                if matches:
                    price_text = matches[0]
                    break

        # Original price (strikethrough)
        orig_el = soup.select_one("[data-testid='product-original-price']") or soup.select_one(".original-price") or soup.select_one(".strikethrough")
        orig_text = orig_el.get_text(strip=True) if orig_el else None

        # Product image - Ajio specific selectors (Amazon-like approach)
        image_url = None
        
        # Try multiple approaches to find the main product image
        img_selectors = [
            # Primary Ajio selectors
            "[data-testid='product-image'] img",
            ".product-image img",
            ".pdp-product-image img",
            "img[alt*='product']",
            "img[src*='ajio']",
            "img[class*='product']",
            "img[data-testid='product-image']",
            ".image-gallery img",
            ".pdp-image img",
            ".product-photo img",
            # Additional Ajio patterns
            "img[class*='pdp']",
            "img[alt*='dress']",
            "img[alt*='shirt']",
            "img[alt*='shoes']",
            "img[alt*='bag']",
            "img[alt*='watch']",
            "img[alt*='jeans']",
            "img[alt*='top']"
        ]
        
        # Try each selector
        for selector in img_selectors:
            img_el = soup.select_one(selector)
            if img_el:
                # Try multiple image attributes
                for attr in ["src", "data-src", "data-lazy", "data-original"]:
                    temp_url = img_el.get(attr)
                    if temp_url and temp_url.strip():
                        # Clean up the image URL
                        if temp_url.startswith("//"):
                            temp_url = "https:" + temp_url
                        elif temp_url.startswith("/"):
                            temp_url = "https://www.ajio.com" + temp_url
                        
                        # Check if it's a valid product image
                        if not any(badge in temp_url.lower() for badge in ['plus_', 'badge_', 'icon_', 'logo_', 'banner_', 'header_', 'footer_', 'sprite', 'placeholder']):
                            image_url = temp_url
                            break
                
                if image_url:
                    break
        
        # If still no image found, try container-based approach
        if not image_url:
            product_containers = [
                ".pdp-product-image",
                ".product-image-container", 
                ".image-gallery",
                ".pdp-image-container",
                "[class*='product-image']",
                "[class*='pdp-image']"
            ]
            
            for container_selector in product_containers:
                container = soup.select_one(container_selector)
                if container:
                    img_el = container.select_one("img")
                    if img_el:
                        for attr in ["src", "data-src", "data-lazy"]:
                            temp_url = img_el.get(attr)
                            if temp_url and temp_url.strip():
                                if temp_url.startswith("//"):
                                    temp_url = "https:" + temp_url
                                elif temp_url.startswith("/"):
                                    temp_url = "https://www.ajio.com" + temp_url
                                
                                if not any(badge in temp_url.lower() for badge in ['plus_', 'badge_', 'icon_', 'logo_', 'banner_', 'header_', 'footer_', 'sprite', 'placeholder']):
                                    image_url = temp_url
                                    break
                        if image_url:
                            break
                if image_url:
                    break

        # Availability
        availability = True
        out_of_stock_indicators = [
            "out of stock", "sold out", "unavailable", "not available"
        ]
        for indicator in out_of_stock_indicators:
            if soup.find(text=re.compile(indicator, re.I)):
                availability = False
                break

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
            "website": "Ajio",
        }
