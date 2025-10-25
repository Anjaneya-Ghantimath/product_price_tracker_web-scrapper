from __future__ import annotations

import re
from typing import Any, Dict

from .base_scraper import BaseScraper, bs4


class FlipkartScraper(BaseScraper):
    def supports(self, url: str) -> bool:
        return "flipkart.com" in url

    async def parse(self, html: str, url: str) -> Dict[str, Any]:
        soup = bs4(html)
        
        # Product title - Flipkart specific selectors
        title_el = soup.select_one("span.B_NuCI") or \
                  soup.select_one("h1.yhB1nd") or \
                  soup.select_one("h1[class*='yhB1nd']") or \
                  soup.select_one("h1") or \
                  soup.select_one("[class*='product-title']") or \
                  soup.select_one(".product-title") or \
                  soup.select_one("h1[data-testid='product-title']")
        title = title_el.get_text(strip=True) if title_el else None

        # Current price - Flipkart specific selectors
        price_el = soup.select_one("div._30jeq3._16Jk6d") or \
                  soup.select_one("div.CEmiEU") or \
                  soup.select_one("div._30jeq3") or \
                  soup.select_one("div[class*='_30jeq3']") or \
                  soup.select_one("div[class*='_16Jk6d']") or \
                  soup.select_one("[class*='price']") or \
                  soup.select_one(".price") or \
                  soup.select_one("div[data-testid='price']") or \
                  soup.select_one("span[class*='_30jeq3']")
        price_text = price_el.get_text(strip=True) if price_el else None
        
        # If no price found with selectors, try to find price patterns in text
        if not price_text:
            import re
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

        # Original price (strikethrough) - Flipkart specific selectors
        orig_el = soup.select_one("div._3I9_wc._2p6lqe") or \
                 soup.select_one("div._3I9_wc") or \
                 soup.select_one("div[class*='_3I9_wc']") or \
                 soup.select_one("[class*='original']") or \
                 soup.select_one(".strikethrough") or \
                 soup.select_one("div[data-testid='original-price']")
        orig_text = orig_el.get_text(strip=True) if orig_el else None

        # Product image - Flipkart specific selectors (more comprehensive approach)
        image_url = None
        
        # Try multiple approaches to find the main product image
        img_selectors = [
            # Primary Flipkart selectors
            "img._396cs4._2amPTt._3qGmMb",
            "img.q6DClP",
            "img._396cs4",
            "img._2amPTt", 
            "img._3qGmMb",
            # Generic product image selectors
            "img[alt*='product']",
            "img[src*='flipkart']",
            "img[data-testid='product-image']",
            ".product-image img",
            "img[class*='product']",
            "img[src*='product']",
            # Common product types
            "img[alt*='shirt']",
            "img[alt*='dress']", 
            "img[alt*='shoes']",
            "img[alt*='mobile']",
            "img[alt*='laptop']",
            "img[alt*='watch']",
            "img[alt*='bag']",
            # Additional Flipkart specific patterns
            "img[class*='_396cs4']",
            "img[class*='_2amPTt']",
            "img[class*='_3qGmMb']",
            # Fallback selectors
            ".pdp-product-image img",
            ".image-gallery img",
            ".pdp-image img",
            ".product-photo img"
        ]
        
        # Try each selector
        for selector in img_selectors:
            img_el = soup.select_one(selector)
            if img_el:
                # Try multiple image attributes
                for attr in ["src", "data-src", "data-old-hires", "data-lazy", "data-original"]:
                    temp_url = img_el.get(attr)
                    if temp_url and temp_url.strip():
                        # Clean up the image URL
                        if temp_url.startswith("//"):
                            temp_url = "https:" + temp_url
                        elif temp_url.startswith("/"):
                            temp_url = "https://www.flipkart.com" + temp_url
                        
                        # Check if it's a valid product image (not UI elements)
                        if not any(badge in temp_url.lower() for badge in ['plus_', 'badge_', 'icon_', 'logo_', 'banner_', 'header_', 'footer_', 'sprite', 'placeholder']):
                            image_url = temp_url
                            break
                
                if image_url:
                    break
        
        # If still no image found, try to find any image in the main product area
        if not image_url:
            # Look for images in common product containers
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
                        for attr in ["src", "data-src", "data-old-hires", "data-lazy"]:
                            temp_url = img_el.get(attr)
                            if temp_url and temp_url.strip():
                                if temp_url.startswith("//"):
                                    temp_url = "https:" + temp_url
                                elif temp_url.startswith("/"):
                                    temp_url = "https://www.flipkart.com" + temp_url
                                
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
            "out of stock", "sold out", "unavailable", "not available", "currently unavailable"
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
            "website": "Flipkart",
        }


