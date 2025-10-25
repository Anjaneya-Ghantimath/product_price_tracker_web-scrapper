from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import List, Optional

import pandas as pd
import plotly.express as px
import streamlit as st
import yaml
from dotenv import load_dotenv
from loguru import logger

from analytics.insights import compute_deal_score, volatility_indicator
from analytics.predictions import simple_price_forecast
from database.db_manager import DatabaseManager
from scrapers.utils import scrape_multiple_products
from utils.helpers import ensure_dirs, generate_fake_price_history
from utils.validators import is_valid_url, sanitize_text


st.set_page_config(page_title="Price Tracker", layout="wide")


@st.cache_resource
def get_config() -> dict:
    # Try different paths to find config.yaml
    config_paths = [
        "config.yaml",  # When running from price_tracker directory
        "price_tracker/config.yaml",  # When running from parent directory
        os.path.join(os.path.dirname(__file__), "config.yaml")  # Relative to this file
    ]
    
    for config_path in config_paths:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
    
    # If no config found, create a default one
    default_config = {
        "app": {
            "name": "Price Tracker",
            "theme": "light",
            "primary_color": "#FF6B6B",
            "secondary_color": "#4ECDC4",
            "quiet_hours": {"start": "23:00", "end": "07:00"}
        },
        "scraping": {
            "default_check_frequency_hours": 6,
            "enable_async": True,
            "rate_limit_seconds": 2,
            "max_concurrency": 8,
            "user_agents": [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
            ],
            "retry": {"max_attempts": 3, "backoff_base_seconds": 1.5}
        },
        "alerts": {
            "enable_email": True,
            "daily_digest": True,
            "throttle_per_product_per_day": 1,
            "thresholds": {"medium_drop_percent": 15, "high_drop_percent": 30, "critical_drop_percent": 50}
        },
        "database": {"path": "./data/products.db", "pool_size": 5},
        "scheduler": {
            "health_check_interval_minutes": 60,
            "cleanup_interval_hours": 24,
            "adaptive": {"stable_hours": 6, "volatile_hours": 2, "above_threshold_hours": 12}
        }
    }
    
    # Save default config
    with open("config.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(default_config, f, sort_keys=False)
    
    return default_config


@st.cache_resource
def get_db(path: str, pool_size: int) -> DatabaseManager:
    return DatabaseManager(path, pool_size)


@st.cache_data
def load_products(_db: DatabaseManager) -> pd.DataFrame:
    rows = _db.list_products(only_active=True)  # Only show active products
    return pd.DataFrame([dict(r) for r in rows])


def seed_demo(db: DatabaseManager) -> None:
    # Only create demo data if no products exist and user explicitly wants it
    if db.list_products():
        return
    # Don't automatically seed demo data - let users add their own products


def save_config(cfg: dict) -> None:
    """Persist config to config.yaml."""
    with open("config.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)


def sidebar(cfg: dict, db: DatabaseManager) -> str:
    with st.sidebar:
        st.markdown("## 🛒 Price Tracker")
        st.markdown("Track product prices with smart alerts.")
        
        # Navigation
        page = st.radio("Navigate", [
            "Dashboard", 
            "Add Products", 
            "Analytics", 
            "Websites",
            "Settings", 
            "Alert History"
        ], index=0, key="navigation_radio")
        
        # Quick stats
        products_df = load_products(db)
        total_products = len(products_df)  # This now only shows active products
        active_products = total_products  # Same as total since we only load active
        total_alerts = len(db.list_alerts())
        
        # Calculate savings (simplified)
        total_savings = 0
        avg_drop = 0
        if not products_df.empty:
            for _, row in products_df.iterrows():
                pid = row.get('id')
                if pid:
                    hist_rows = db.list_price_history(pid, limit=2)
                    if len(hist_rows) >= 2:
                        old_price = hist_rows[1]['price']
                        new_price = hist_rows[0]['price']
                        if old_price and new_price and old_price > new_price:
                            total_savings += (old_price - new_price)
                            avg_drop += ((old_price - new_price) / old_price) * 100
        
        if total_products > 0:
            avg_drop = avg_drop / total_products
        
        # Stats display
        st.markdown("### 📊 Quick Stats")
        c1, c2 = st.columns(2)
        with c1:
            st.metric("Total Products", total_products)
            st.metric("Active Products", active_products)
        with c2:
            st.metric("Total Alerts", total_alerts)
            st.metric("Total Savings", f"₹{total_savings:,.0f}")
        
        # Website breakdown
        if not products_df.empty:
            st.markdown("### 🌐 By Website")
            website_counts = products_df['website'].value_counts()
            for website, count in website_counts.items():
                if website:
                    website_icons = {
                        'Amazon': '🛒',
                        'Flipkart': '🛍️', 
                        'Snapdeal': '📦',
                        'Meesho': '👗',
                        'Myntra': '👔',
                        'Nykaa': '💄',
                        'Ajio': '👕',
                        'JioMart': '🛒'
                    }
                    icon = website_icons.get(website, '🌐')
                    st.caption(f"{icon} {website}: {count}")
        
        # Quick actions
        st.markdown("### ⚡ Quick Actions")
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    
    return page


def render_dashboard(cfg: dict, db: DatabaseManager) -> None:
    st.markdown("### 📊 Dashboard")
    products_df = load_products(db)
    if products_df.empty:
        st.info("No products yet. Add some from the Add Products page.")
        return

    # Filters and search
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    with col1:
        q = st.text_input("🔍 Search by name or URL", placeholder="Search products...")
    with col2:
        site = st.selectbox("Website", ["All"] + sorted([x for x in products_df["website"].dropna().unique()]))
    with col3:
        sort_by = st.selectbox("Sort by", ["Latest", "Price", "Discount", "Deal Score"])
    with col4:
        view_mode = st.selectbox("View", ["Grid", "List"])
    
    # Apply filters
    if q:
        products_df = products_df[products_df["name"].fillna("").str.contains(q, case=False) | products_df["url"].str.contains(q, case=False)]
    if site != "All":
        products_df = products_df[products_df["website"] == site]

    # Sort products
    if sort_by == "Price":
        products_df = products_df.sort_values("id", ascending=False)  # Will sort by current price in display
    elif sort_by == "Latest":
        products_df = products_df.sort_values("date_added", ascending=False)
    elif sort_by == "Discount":
        products_df = products_df.sort_values("id", ascending=False)  # Will sort by discount in display
    elif sort_by == "Deal Score":
        products_df = products_df.sort_values("id", ascending=False)  # Will sort by deal score in display

    # Product display
    if view_mode == "Grid":
        # Grid view with 2 columns
        cols = st.columns(2)
        for idx, (_, row) in enumerate(products_df.iterrows()):
            with cols[idx % 2]:
                render_product_card(row, db)
    else:
        # List view
        for _, row in products_df.iterrows():
            render_product_card(row, db, is_list=True)

def render_product_card(row, db: DatabaseManager, is_list: bool = False) -> None:
    """Render a single product card."""
    pid = int(row["id"]) if row.get("id") is not None else None
    hist_rows = db.list_price_history(pid, limit=30) if pid else []
    hdf = pd.DataFrame([dict(r) for r in hist_rows])
    
    if not hdf.empty:
        hdf['timestamp'] = pd.to_datetime(hdf['timestamp'])
        hdf = hdf.sort_values('timestamp')
        current = hdf['price'].iloc[-1]
        original = hdf['original_price'].iloc[-1] if hdf['original_price'].notna().any() else None
        discount = hdf['discount_percent'].iloc[-1] if hdf['discount_percent'].notna().any() else None
        avail = bool(hdf['availability'].iloc[-1])
        score = compute_deal_score(hdf, current, discount, avail)
    else:
        current = original = discount = None
        avail = True
        score = 0

    # Product card container
    with st.container(border=True):
        if is_list:
            # List view layout
            col_img, col_info, col_actions = st.columns([1, 3, 1])
        else:
            # Grid view layout
            col_img, col_info, col_actions = st.columns([1, 2, 1])
        
        with col_img:
            # Product image
            image_path = row.get("image_path")
            if image_path:
                # Try different possible paths
                possible_paths = [
                    image_path,
                    f"price_tracker/{image_path}",
                    f"static/images/{os.path.basename(image_path)}"
                ]
                
                image_found = False
                for path in possible_paths:
                    if os.path.exists(path):
                        try:
                            st.image(path, width=120 if is_list else 100)
                            image_found = True
                            break
                        except Exception:
                            continue
                
                if not image_found:
                    # Show placeholder with website info
                    website = row.get('website', 'Unknown')
                    st.image(f"https://placehold.co/150x150?text={website}", width=120 if is_list else 100)
            else:
                # Show placeholder with website info
                website = row.get('website', 'Unknown')
                st.image(f"https://placehold.co/150x150?text={website}", width=120 if is_list else 100)
        
        with col_info:
            # Product details
            name = sanitize_text(row.get('name') or 'Product', 80 if is_list else 50)
            st.markdown(f"**{name}**")
            
            website = row.get('website') or 'Unknown'
            website_icons = {
                'Amazon': '🛒',
                'Flipkart': '🛍️', 
                'Snapdeal': '📦',
                'Meesho': '👗',
                'Myntra': '👔',
                'Nykaa': '💄',
                'Ajio': '👕',
                'JioMart': '🛒'
            }
            icon = website_icons.get(website, '🌐')
            st.caption(f"{icon} {website}")
            
            # Price information
            if current:
                st.metric("Current Price", f"₹{current:,.0f}")
                if discount and discount > 0:
                    st.metric("Discount", f"{discount:.1f}%", delta=f"-{discount:.1f}%")
                else:
                    st.metric("Discount", "0%")
            
            # Deal score with color coding
            if score >= 80:
                score_color = "🟢"
            elif score >= 60:
                score_color = "🟡"
            else:
                score_color = "🔴"
            
            st.markdown(f"{score_color} Deal Score: {score}/100")
            st.progress(min(1.0, score / 100.0))
            
            # Status indicator
            status = "🟢 In Stock" if avail else "🔴 Out of Stock"
            st.caption(status)
        
        with col_actions:
            # Mini price chart
            if not hdf.empty and len(hdf) > 1:
                fig = px.line(hdf.tail(7), x='timestamp', y='price', height=100)
                fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), showlegend=False)
                fig.update_xaxes(visible=False)
                fig.update_yaxes(visible=False)
                st.plotly_chart(fig, use_container_width=True)
            
            # Action buttons - using simple layout
            st.link_button("🛒 Buy Now", row["url"], use_container_width=True)
            
            if st.button("📊 Analytics", key=f"analytics_{pid}", use_container_width=True):
                st.session_state.selected_product_for_analytics = pid
                st.session_state.analytics_clicked = True
                st.rerun()
            
            if st.button("🗑️ Remove", key=f"remove_{pid}", use_container_width=True):
                if st.session_state.get(f"confirm_remove_{pid}", False):
                    # Actually remove the product from database
                    try:
                        # Delete price history first (foreign key constraint)
                        with db.get_conn() as conn:
                            cur = conn.cursor()
                            cur.execute("DELETE FROM price_history WHERE product_id=?", (pid,))
                            cur.execute("DELETE FROM alerts WHERE product_id=?", (pid,))
                            cur.execute("DELETE FROM products WHERE id=?", (pid,))
                            conn.commit()
                        
                        # Clear cache to refresh the dashboard
                        st.cache_data.clear()
                        
                        st.success("Product removed successfully!")
                        # Clear confirmation state
                        if f"confirm_remove_{pid}" in st.session_state:
                            del st.session_state[f"confirm_remove_{pid}"]
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to remove product: {e}")
                else:
                    st.session_state[f"confirm_remove_{pid}"] = True
                    st.warning("Click again to confirm removal")
            
            if st.button("✏️ Edit", key=f"edit_{pid}", use_container_width=True):
                st.session_state[f"edit_product_{pid}"] = True
                st.rerun()
        
        # Edit product form (if edit button was clicked)
        if st.session_state.get(f"edit_product_{pid}", False):
            with st.expander("✏️ Edit Product", expanded=True):
                with st.form(f"edit_form_{pid}"):
                    new_name = st.text_input("Product Name", value=row.get('name') or '')
                    threshold_value = row.get('user_threshold')
                    if threshold_value is None:
                        threshold_value = 0.0
                    else:
                        threshold_value = float(threshold_value)
                    new_threshold = st.number_input("Price Threshold (₹)", value=threshold_value, min_value=0.0, step=0.01)
                    new_category = st.text_input("Category", value=row.get('category') or '')
                    
                    if st.form_submit_button("💾 Save Changes"):
                        updates = {}
                        if new_name:
                            updates['name'] = new_name
                        if new_threshold > 0:
                            updates['user_threshold'] = new_threshold
                        if new_category:
                            updates['category'] = new_category
                        
                        if updates:
                            db.update_product(pid, updates)
                            st.success("Product updated!")
                            del st.session_state[f"edit_product_{pid}"]
                            st.rerun()
                    
                    if st.form_submit_button("❌ Cancel"):
                        del st.session_state[f"edit_product_{pid}"]
                        st.rerun()
        
        st.divider()


def download_image(url: str, product_id: int) -> str:
    """Download and save product image locally."""
    try:
        import requests
        from PIL import Image
        import io
        
        if not url or url.strip() == "":
            return None
            
        # Clean URL
        url = url.strip()
        if not url.startswith(('http://', 'https://')):
            return None
        
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        if response.status_code == 200 and len(response.content) > 1000:  # Ensure it's not a small error page
            # Create static/images directory if it doesn't exist
            os.makedirs("static/images", exist_ok=True)
            
            # Save image with proper extension
            image_path = f"static/images/product_{product_id}.jpg"
            with open(image_path, 'wb') as f:
                f.write(response.content)
            
            # Verify the image is valid
            try:
                with Image.open(image_path) as img:
                    img.verify()
                return image_path
            except Exception:
                # If image is invalid, delete it
                if os.path.exists(image_path):
                    os.remove(image_path)
                return None
    except Exception as e:
        logger.warning(f"Failed to download image from {url}: {e}")
    return None

def render_add_products(cfg: dict, db: DatabaseManager) -> None:
    st.markdown("### ➕ Add Products")
    
    # Bulk URL input
    st.subheader("Bulk Add Products")
    urls_text = st.text_area("Paste product URLs (one per line)", 
                            placeholder="https://www.amazon.in/dp/B0CHX2Z5H3\nhttps://www.flipkart.com/p/itm4f5474d1f")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        scrape_and_add = st.checkbox("Scrape product details automatically", value=True)
    with col2:
        user_threshold = st.number_input("Default price threshold (₹)", min_value=0.0, value=0.0, step=0.01)
    
    if st.button("Add Products", type="primary"):
        if not urls_text.strip():
            st.error("Please enter at least one URL.")
            return
            
        urls = [u.strip() for u in urls_text.splitlines() if u.strip()]
        good_urls = [u for u in urls if is_valid_url(u)]
        bad_urls = set(urls) - set(good_urls)
        
        if bad_urls:
            for u in bad_urls:
                st.warning(f"Invalid URL skipped: {u}")
        
        if not good_urls:
            st.error("No valid URLs to process.")
            return
        
        if scrape_and_add:
            # Scrape product details
            with st.spinner("🔍 Scraping product details..."):
                try:
                    cfg_s = cfg["scraping"]
                    scraped_data = asyncio.run(
                        scrape_multiple_products(
                            good_urls,
                            user_agents=cfg_s["user_agents"],
                            rate_limit_seconds=cfg_s["rate_limit_seconds"],
                            max_concurrency=cfg_s["max_concurrency"],
                            max_attempts=cfg_s["retry"]["max_attempts"],
                            backoff_base=cfg_s["retry"]["backoff_base_seconds"],
                        )
                    )
                    
                    # Debug: Show what was scraped
                    if scraped_data:
                        st.success(f"✅ Successfully scraped {len(scraped_data)} products")
                        for i, data in enumerate(scraped_data):
                            title = data.get('title', 'No title')
                            price = data.get('current_price', 'No price')
                            website = data.get('website', 'Unknown')
                            st.write(f"📦 {title} - ₹{price} ({website})")
                    else:
                        st.warning("⚠️ No products were scraped. Check if URLs are valid and accessible.")
                        
                except Exception as e:
                    st.error(f"❌ Scraping failed: {e}")
                    st.error("💡 Try checking if the URLs are accessible and the websites are not blocking requests.")
                    return
            
            # Add scraped products to database
            added_count = 0
            for data in scraped_data:
                try:
                    # Determine website from URL
                    website = "Unknown"
                    if "amazon." in data["url"]:
                        website = "Amazon"
                    elif "flipkart.com" in data["url"]:
                        website = "Flipkart"
                    elif "snapdeal.com" in data["url"]:
                        website = "Snapdeal"
                    elif "meesho.com" in data["url"]:
                        website = "Meesho"
                    elif "myntra.com" in data["url"]:
                        website = "Myntra"
                    elif "nykaa.com" in data["url"]:
                        website = "Nykaa"
                    elif "ajio.com" in data["url"]:
                        website = "Ajio"
                    elif "jiomart.com" in data["url"]:
                        website = "JioMart"
                    
                    # Add product to database
                    pid = db.add_product(
                        url=data["url"],
                        name=sanitize_text(data.get("title")),
                        website=website,
                        category=None,
                        image_path=None,
                        user_threshold=user_threshold if user_threshold > 0 else None,
                        check_frequency=6
                    )
                    
                    # Download and save image
                    if data.get("image_url"):
                        image_path = download_image(data["image_url"], pid)
                        if image_path:
                            db.update_product(pid, {"image_path": image_path})
                    
                    # Add initial price history
                    if data.get("current_price"):
                        db.add_price_history(
                            pid,
                            data["current_price"],
                            data.get("original_price"),
                            data.get("discount_percent"),
                            data.get("availability", True)
                        )
                    
                    added_count += 1
                    
                except Exception as e:
                    st.error(f"Failed to add product {data.get('url', 'unknown')}: {e}")
            
            st.success(f"Successfully added {added_count} products with scraped data!")
        else:
            # Add URLs without scraping
            for url in good_urls:
                try:
                    db.add_product(
                        url=url,
                        name=None,
                        website=None,
                        category=None,
                        image_path=None,
                        user_threshold=user_threshold if user_threshold > 0 else None,
                        check_frequency=6
                    )
                except Exception as e:
                    st.error(f"Failed to add URL {url}: {e}")
            
            st.success(f"Added {len(good_urls)} URLs (without scraping)")
        
        # Clear cache to refresh dashboard
        st.cache_data.clear()
        st.rerun()

    st.divider()
    
    # Single URL preview
    st.subheader("Preview Single Product")
    demo_url = st.text_input("Enter a single URL to preview scrape", 
                            placeholder="https://www.amazon.in/dp/B0CHX2Z5H3 or https://www.flipkart.com/p/itm4f5474d1f")
    
    if st.button("Preview Scrape") and demo_url:
        if not is_valid_url(demo_url):
            st.error("Invalid URL format.")
            return
            
        with st.spinner("🔍 Scraping product details..."):
            try:
                cfg_s = cfg["scraping"]
                data = asyncio.run(
                    scrape_multiple_products(
                        [demo_url],
                        user_agents=cfg_s["user_agents"],
                        rate_limit_seconds=cfg_s["rate_limit_seconds"],
                        max_concurrency=cfg_s["max_concurrency"],
                        max_attempts=cfg_s["retry"]["max_attempts"],
                        backoff_base=cfg_s["retry"]["backoff_base_seconds"],
                    )
                )
                
                if data and len(data) > 0:
                    st.success("✅ Scraping successful!")
                    
                    # Display scraped data in a nice format
                    product_data = data[0]
                    
                    col1, col2 = st.columns([1, 1])
                    with col1:
                        if product_data.get("image_url"):
                            try:
                                # Validate and clean image URL
                                image_url = product_data["image_url"]
                                # Handle relative URLs
                                if image_url.startswith("//"):
                                    image_url = "https:" + image_url
                                elif image_url.startswith("/"):
                                    # Extract domain from the original URL
                                    from urllib.parse import urlparse
                                    parsed = urlparse(demo_url)
                                    image_url = f"{parsed.scheme}://{parsed.netloc}{image_url}"
                                
                                st.image(image_url, width=200)
                            except Exception as e:
                                st.warning(f"Could not load image: {str(e)[:100]}...")
                                st.info("No image available")
                        else:
                            st.info("No image found")
                    
                    with col2:
                        st.markdown(f"**Title:** {product_data.get('title', 'N/A')}")
                        st.markdown(f"**Website:** {product_data.get('website', 'Unknown')}")
                        st.markdown(f"**Current Price:** ₹{product_data.get('current_price', 'N/A')}")
                        st.markdown(f"**Original Price:** ₹{product_data.get('original_price', 'N/A')}")
                        
                        # Fix the discount formatting issue
                        discount = product_data.get('discount_percent')
                        if discount is not None and discount != 0:
                            st.markdown(f"**Discount:** {discount:.1f}%")
                        else:
                            st.markdown("**Discount:** 0%")
                        
                        st.markdown(f"**Availability:** {'In Stock' if product_data.get('availability') else 'Out of Stock'}")
                    
                    # Add to database button
                    if st.button("Add This Product", type="primary"):
                        try:
                            pid = db.add_product(
                                url=product_data["url"],
                                name=sanitize_text(product_data.get("title")),
                                website=product_data.get("website"),
                                category=None,
                                image_path=None,
                                user_threshold=user_threshold if user_threshold > 0 else None,
                                check_frequency=6
                            )
                            
                            # Download image
                            if product_data.get("image_url"):
                                image_path = download_image(product_data["image_url"], pid)
                                if image_path:
                                    db.update_product(pid, {"image_path": image_path})
                            
                            # Add price history
                            if product_data.get("current_price"):
                                db.add_price_history(
                                    pid,
                                    product_data["current_price"],
                                    product_data.get("original_price"),
                                    product_data.get("discount_percent"),
                                    product_data.get("availability", True)
                                )
                            
                            st.success("Product added successfully!")
                            # Clear cache to refresh dashboard
                            st.cache_data.clear()
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"Failed to add product: {e}")
                else:
                    st.error("❌ Failed to scrape product details.")
                    st.error("💡 Try checking if the URL is accessible and the website is not blocking requests.")
                    
            except Exception as e:
                st.error(f"❌ Scraping failed: {e}")
                st.error("💡 This might be due to network issues or website blocking.")


def render_analytics(cfg: dict, db: DatabaseManager) -> None:
    st.markdown("### 📈 Analytics")
    
    # Add back button if came from dashboard
    if hasattr(st.session_state, 'selected_product_for_analytics'):
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("← Back to Dashboard", type="secondary"):
                del st.session_state.selected_product_for_analytics
                st.session_state.back_to_dashboard = True
                st.rerun()
        with col2:
            st.markdown("**Product Analytics**")
    
    products_df = load_products(db)
    if products_df.empty:
        st.info("No products to analyze.")
        return
    
    # Check if product was selected from dashboard
    if hasattr(st.session_state, 'selected_product_for_analytics'):
        product_id = st.session_state.selected_product_for_analytics
        # Don't clear the session state yet - keep it for back navigation
    else:
        # Product selection
        product_options = []
        for _, row in products_df.iterrows():
            name = row.get('name') or f"Product {row['id']}"
            product_options.append(f"{name} (ID: {row['id']})")
        
        selected_product = st.selectbox("Select product", product_options)
        if not selected_product:
            return
        
        # Extract product ID
        product_id = int(selected_product.split("(ID: ")[1].split(")")[0])
    
    # Get price history
    hist_rows = db.list_price_history(product_id)
    if not hist_rows:
        st.warning("No price history available for this product.")
        return
    
    hdf = pd.DataFrame([dict(r) for r in hist_rows])
    hdf['timestamp'] = pd.to_datetime(hdf['timestamp'])
    hdf = hdf.sort_values('timestamp')
    
    if hdf.empty:
        st.warning("No history data available.")
        return
    
    # Current metrics
    current_price = hdf['price'].iloc[-1]
    original_price = hdf['original_price'].iloc[-1] if hdf['original_price'].notna().any() else None
    discount_percent = hdf['discount_percent'].iloc[-1] if hdf['discount_percent'].notna().any() else None
    availability = hdf['availability'].iloc[-1]
    
    # Display metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Current Price", f"₹{current_price:,.2f}")
    with col2:
        st.metric("Original Price", f"₹{original_price:,.2f}" if original_price else "N/A")
    with col3:
        st.metric("Discount", f"{discount_percent:.1f}%" if discount_percent else "0%")
    with col4:
        st.metric("Status", "In Stock" if availability else "Out of Stock")
    
    # Price trend chart
    st.subheader("Price Trend")
    fig = px.line(hdf, x='timestamp', y='price', title='Price History', 
                  labels={'price': 'Price (₹)', 'timestamp': 'Date'})
    st.plotly_chart(fig, use_container_width=True)
    
    # 7-day forecast
    st.subheader("7-Day Price Forecast")
    prices = hdf['price'].tolist()
    if len(prices) >= 2:
        forecast = simple_price_forecast(prices, 7)
        
        # Create forecast dates
        last_date = hdf['timestamp'].iloc[-1]
        forecast_dates = [last_date + pd.Timedelta(days=i+1) for i in range(7)]
        
        # Create forecast dataframe
        forecast_df = pd.DataFrame({
            'timestamp': forecast_dates,
            'price': forecast,
            'type': 'forecast'
        })
        
        # Combine with history for visualization
        history_df = hdf[['timestamp', 'price']].copy()
        history_df['type'] = 'history'
        
        combined_df = pd.concat([history_df, forecast_df])
        
        # Plot combined chart
        fig_forecast = px.line(combined_df, x='timestamp', y='price', color='type',
                              title='Price History and 7-Day Forecast',
                              labels={'price': 'Price (₹)', 'timestamp': 'Date'})
        st.plotly_chart(fig_forecast, use_container_width=True)
        
        # Show forecast values
        st.write("**Forecasted Prices:**")
        for i, (date, price) in enumerate(zip(forecast_dates, forecast)):
            st.write(f"Day {i+1} ({date.strftime('%Y-%m-%d')}): ₹{price:,.2f}")
    else:
        st.warning("Need at least 2 price points for forecasting.")
    
    # Deal score and volatility
    st.subheader("Product Insights")
    deal_score = compute_deal_score(hdf, current_price, discount_percent, availability)
    volatility = volatility_indicator(hdf)
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Deal Score", f"{deal_score}/100")
        st.progress(deal_score/100, text=f"Deal Score: {deal_score}/100")
    with col2:
        st.metric("Price Volatility", f"{volatility:.2f}%")
    
    # Price statistics
    st.subheader("Price Statistics")
    stats_col1, stats_col2, stats_col3 = st.columns(3)
    with stats_col1:
        st.metric("Highest Price", f"₹{hdf['price'].max():,.2f}")
    with stats_col2:
        st.metric("Lowest Price", f"₹{hdf['price'].min():,.2f}")
    with stats_col3:
        st.metric("Average Price", f"₹{hdf['price'].mean():,.2f}")


def render_settings(cfg: dict, db: DatabaseManager) -> None:
    st.markdown("### ⚙️ Settings")
    with st.form("settings_form"):
        st.markdown("#### Scraping")
        col1, col2, col3 = st.columns(3)
        with col1:
            default_freq = st.number_input("Default check freq (hours)", min_value=1, max_value=48, value=int(cfg["scraping"]["default_check_frequency_hours"]))
        with col2:
            enable_async = st.toggle("Enable async scraping", value=bool(cfg["scraping"]["enable_async"]))
        with col3:
            rate_limit = st.number_input("Rate limit (sec)", min_value=0.0, max_value=10.0, value=float(cfg["scraping"]["rate_limit_seconds"]))

        col4, col5 = st.columns(2)
        with col4:
            max_conc = st.number_input("Max concurrency", min_value=1, max_value=32, value=int(cfg["scraping"]["max_concurrency"]))
        with col5:
            retries = st.number_input("Max retry attempts", min_value=1, max_value=6, value=int(cfg["scraping"]["retry"]["max_attempts"]))

        st.markdown("#### Alerts")
        col6, col7, col8 = st.columns(3)
        with col6:
            enable_email = st.toggle("Enable email alerts", value=bool(cfg["alerts"]["enable_email"]))
        with col7:
            daily_digest = st.toggle("Daily digest", value=bool(cfg["alerts"]["daily_digest"]))
        with col8:
            throttle = st.number_input("Max alerts/product/day", min_value=0, max_value=10, value=int(cfg["alerts"]["throttle_per_product_per_day"]))

        st.markdown("Quiet hours")
        q1, q2 = st.columns(2)
        with q1:
            quiet_start = st.text_input("Start (HH:MM)", value=str(cfg["app"]["quiet_hours"]["start"]))
        with q2:
            quiet_end = st.text_input("End (HH:MM)", value=str(cfg["app"]["quiet_hours"]["end"]))

        submitted = st.form_submit_button("Save settings")
        if submitted:
            cfg["scraping"]["default_check_frequency_hours"] = int(default_freq)
            cfg["scraping"]["enable_async"] = bool(enable_async)
            cfg["scraping"]["rate_limit_seconds"] = float(rate_limit)
            cfg["scraping"]["max_concurrency"] = int(max_conc)
            cfg["scraping"]["retry"]["max_attempts"] = int(retries)
            cfg["alerts"]["enable_email"] = bool(enable_email)
            cfg["alerts"]["daily_digest"] = bool(daily_digest)
            cfg["alerts"]["throttle_per_product_per_day"] = int(throttle)
            cfg["app"]["quiet_hours"]["start"] = quiet_start
            cfg["app"]["quiet_hours"]["end"] = quiet_end
            save_config(cfg)
            st.success("Settings saved. Reloading...")
            st.rerun()


def render_websites(cfg: dict, db: DatabaseManager) -> None:
    st.markdown("### 🌐 Products by Website")
    products_df = load_products(db)
    
    if products_df.empty:
        st.info("No products yet. Add some from the Add Products page.")
        return
    
    # Get unique websites
    websites = products_df['website'].dropna().unique()
    if len(websites) == 0:
        st.info("No website information available.")
        return
    
    # Website selector
    selected_website = st.selectbox("Select Website", websites)
    
    # Filter products by website
    website_products = products_df[products_df['website'] == selected_website]
    
    if website_products.empty:
        st.info(f"No products found for {selected_website}")
        return
    
    # Website stats
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Products", len(website_products))
    with col2:
        st.metric("Active Products", len(website_products))  # All are active since we only load active
    with col3:
        # Calculate average price for this website
        avg_price = 0
        for _, row in website_products.iterrows():
            pid = row.get('id')
            if pid:
                latest_price = db.latest_price(pid)
                if latest_price and latest_price['price']:
                    avg_price += latest_price['price']
        if len(website_products) > 0:
            avg_price = avg_price / len(website_products)
        st.metric("Avg Price", f"₹{avg_price:,.0f}")
    with col4:
        # Calculate total savings for this website
        total_savings = 0
        for _, row in website_products.iterrows():
            pid = row.get('id')
            if pid:
                hist_rows = db.list_price_history(pid, limit=2)
                if len(hist_rows) >= 2:
                    old_price = hist_rows[1]['price']
                    new_price = hist_rows[0]['price']
                    if old_price and new_price and old_price > new_price:
                        total_savings += (old_price - new_price)
        st.metric("Total Savings", f"₹{total_savings:,.0f}")
    
    # Website icon and description
    website_icons = {
        'Amazon': '🛒',
        'Flipkart': '🛍️', 
        'Snapdeal': '📦',
        'Meesho': '👗',
        'Myntra': '👔',
        'Nykaa': '💄',
        'Ajio': '👕',
        'JioMart': '🛒'
    }
    icon = website_icons.get(selected_website, '🌐')
    st.markdown(f"### {icon} {selected_website} Products")
    
    # Display products for this website
    for _, row in website_products.iterrows():
        render_product_card(row, db, is_list=True)

def render_alert_history(cfg: dict, db: DatabaseManager) -> None:
    """Render comprehensive alert history with integrated email management."""
    st.markdown("### 📬 Alert History & Email Management")
    
    # Quick overview of existing emails
    st.markdown("#### 📊 Email Overview")
    gmail_accounts = db.get_gmail_accounts(active_only=False)
    subscribers = db.get_email_subscribers(active_only=False)
    active_subscribers = db.get_email_subscribers(active_only=True)
    default_account = db.get_default_gmail_account()
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📧 Gmail Accounts", len(gmail_accounts))
        if default_account:
            st.caption(f"Default: {default_account.email}")
    with col2:
        st.metric("👥 Total Subscribers", len(subscribers))
    with col3:
        st.metric("✅ Active Subscribers", len(active_subscribers))
    with col4:
        if subscribers:
            active_rate = (len(active_subscribers) / len(subscribers)) * 100
            st.metric("📈 Active Rate", f"{active_rate:.1f}%")
        else:
            st.metric("📈 Active Rate", "0%")
    
    st.divider()
    
    # Create tabs for different sections
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📧 Alert History", "👥 Email Subscribers", "⏰ Alert Schedules", "📧 Gmail Accounts", "📧 Gmail Setup", "📊 Email Stats"])
    
    with tab1:
        st.markdown("#### 📧 Alert History")
        
        # Get alerts from database
        alerts = db.list_alerts()
        
        if not alerts:
            st.info("No alerts generated yet. Alerts will appear here when price thresholds are met.")
        else:
            # Convert to DataFrame for better display
            alerts_df = pd.DataFrame([dict(alert) for alert in alerts])
            alerts_df['timestamp'] = pd.to_datetime(alerts_df['timestamp'])
            alerts_df = alerts_df.sort_values('timestamp', ascending=False)
            
            # Filters
            col1, col2, col3 = st.columns(3)
            with col1:
                alert_type_filter = st.selectbox("Filter by Type", ["All"] + list(alerts_df['alert_type'].unique()))
            with col2:
                read_status = st.selectbox("Filter by Status", ["All", "Unread", "Read"])
            with col3:
                date_range = st.selectbox("Time Range", ["All", "Last 7 days", "Last 30 days"])
            
            # Apply filters
            filtered_df = alerts_df.copy()
            if alert_type_filter != "All":
                filtered_df = filtered_df[filtered_df['alert_type'] == alert_type_filter]
            if read_status == "Unread":
                filtered_df = filtered_df[filtered_df['is_read'] == 0]
            elif read_status == "Read":
                filtered_df = filtered_df[filtered_df['is_read'] == 1]
            if date_range == "Last 7 days":
                cutoff = pd.Timestamp.now() - pd.Timedelta(days=7)
                filtered_df = filtered_df[filtered_df['timestamp'] >= cutoff]
            elif date_range == "Last 30 days":
                cutoff = pd.Timestamp.now() - pd.Timedelta(days=30)
                filtered_df = filtered_df[filtered_df['timestamp'] >= cutoff]
            
            # Display alerts
            st.subheader(f"Alerts ({len(filtered_df)} found)")
            
            for _, alert in filtered_df.iterrows():
                with st.container(border=True):
                    col1, col2, col3 = st.columns([3, 1, 1])
                    
                    with col1:
                        # Alert type with icon
                        alert_icons = {
                            'threshold': '🎯',
                            'percentage': '📉',
                            'low': '🔥',
                            'stock': '📦'
                        }
                        icon = alert_icons.get(alert['alert_type'], '📢')
                        st.markdown(f"{icon} **{alert['alert_type'].title()} Alert**")
                        st.write(alert['message'])
                        st.caption(f"Price at alert: ₹{alert['price_at_alert']:,.2f}" if alert['price_at_alert'] else "No price data")
                    
                    with col2:
                        st.metric("Date", alert['timestamp'].strftime('%Y-%m-%d'))
                        st.metric("Time", alert['timestamp'].strftime('%H:%M'))
                    
                    with col3:
                        if alert['is_read']:
                            st.success("✅ Read")
                        else:
                            st.warning("🔔 Unread")
                        
                        if not alert['is_read']:
                            if st.button("Mark as Read", key=f"read_{alert['id']}"):
                                db.mark_alert_read(alert['id'])
                                st.rerun()
            
            # Summary statistics
            st.subheader("Alert Summary")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Alerts", len(alerts_df))
            with col2:
                st.metric("Unread Alerts", len(alerts_df[alerts_df['is_read'] == 0]))
            with col3:
                st.metric("This Week", len(alerts_df[alerts_df['timestamp'] >= pd.Timestamp.now() - pd.Timedelta(days=7)]))
            with col4:
                st.metric("This Month", len(alerts_df[alerts_df['timestamp'] >= pd.Timestamp.now() - pd.Timedelta(days=30)]))
        
        # Manual alert sending section
        st.subheader("📧 Send Updates")
        st.markdown("Send alerts to all active subscribers")
        
        col1, col2 = st.columns([2, 1])
        with col1:
            test_product_name = st.text_input("Product Name", value="Test Product", key="test_product_name")
            test_price = st.number_input("Price (₹)", value=999.99, min_value=0.0, step=0.01, key="test_price")
            test_message = st.text_area("Alert Message", value="This is a test alert from Price Tracker!", key="test_message")
            
            # Quick action buttons
            col_quick1, col_quick2, col_quick3 = st.columns(3)
            with col_quick1:
                if st.button("📧 Send Test Alert", type="primary"):
                    if db.get_email_subscribers(active_only=True):
                        try:
                            test_product = {
                                "name": test_product_name,
                                "current_price": test_price,
                                "original_price": test_price * 1.2,
                                "discount_percent": 16.7,
                                "website": "Test Store",
                                "url": "https://example.com",
                                "availability": True
                            }
                            
                            send_alert_to_subscribers(test_product, test_message, db)
                            st.success("✅ Test alert sent to all subscribers!")
                        except Exception as e:
                            st.error(f"❌ Failed to send test alert: {e}")
                    else:
                        st.error("❌ No active subscribers to send alerts to")
            
            with col_quick2:
                if st.button("🔄 Send All Product Updates"):
                    if db.get_email_subscribers(active_only=True):
                        try:
                            products_df = load_products(db)
                            sent_count = 0
                            for _, product in products_df.iterrows():
                                # Get current price from latest price history
                                price_history = db.list_price_history(product['id'])
                                if price_history:
                                    # Handle both dataclass and Row objects
                                    latest_price_entry = price_history[-1]
                                    if hasattr(latest_price_entry, 'price'):
                                        latest_price = latest_price_entry.price
                                    else:
                                        # It's a sqlite3.Row object
                                        latest_price = latest_price_entry['price']
                                else:
                                    latest_price = 0.0
                                
                                # Create product data with all required fields
                                product_data = {
                                    "id": product['id'],
                                    "name": product.get('name', 'Unknown Product'),
                                    "current_price": latest_price,
                                    "original_price": latest_price * 1.2,  # Estimate original price
                                    "discount_percent": 0.0,
                                    "website": product.get('website', 'Unknown'),
                                    "url": product.get('url', ''),
                                    "availability": True
                                }
                                
                                alert_msg = f"Price update for {product_data['name']}: ₹{latest_price}"
                                send_alert_to_subscribers(product_data, alert_msg, db)
                                sent_count += 1
                            st.success(f"✅ Sent updates for {sent_count} products!")
                        except Exception as e:
                            st.error(f"❌ Failed to send product updates: {e}")
                    else:
                        st.error("❌ No active subscribers to send alerts to")
            
            with col_quick3:
                if st.button("📊 Send Weekly Summary"):
                    if db.get_email_subscribers(active_only=True):
                        try:
                            # Create weekly summary
                            products_df = load_products(db)
                            summary_msg = f"Weekly Price Tracker Summary:\n\nTracked Products: {len(products_df)}\nActive Subscribers: {len(db.get_email_subscribers(active_only=True))}\n\nKeep tracking for the best deals!"
                            
                            summary_product = {
                                "name": "Weekly Price Tracker Summary",
                                "current_price": 0.00,
                                "original_price": 0.00,
                                "discount_percent": 0.0,
                                "website": "Price Tracker",
                                "url": "https://github.com/your-repo/price-tracker",
                                "availability": True
                            }
                            
                            send_alert_to_subscribers(summary_product, summary_msg, db)
                            st.success("✅ Weekly summary sent to all subscribers!")
                        except Exception as e:
                            st.error(f"❌ Failed to send weekly summary: {e}")
                    else:
                        st.error("❌ No active subscribers to send alerts to")
        
        with col2:
            st.markdown("**Send to:**")
            subscribers = db.get_email_subscribers(active_only=True)
            if subscribers:
                st.write(f"📧 **{len(subscribers)} Active Subscribers:**")
                for sub in subscribers:
                    st.write(f"• {sub.email}")
            else:
                st.warning("No active subscribers")
            
            st.markdown("**Gmail Account:**")
            default_account = db.get_default_gmail_account()
            if default_account:
                st.success(f"✅ {default_account.email}")
            else:
                st.error("❌ No default Gmail account")
    
    with tab2:
        st.markdown("#### 👥 Email Subscribers")
        
        # Show existing subscribers
        existing_subscribers = db.get_email_subscribers(active_only=False)
        if existing_subscribers:
            st.markdown("#### 📋 Existing Email Subscribers")
            for subscriber in existing_subscribers:
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.write(f"📧 **{subscriber.email}**")
                    if subscriber.name:
                        st.caption(f"👤 {subscriber.name}")
                with col2:
                    status = "✅ Active" if subscriber.is_active else "❌ Inactive"
                    st.write(status)
                with col3:
                    st.caption(f"Added: {subscriber.created_at[:10] if subscriber.created_at else 'Unknown'}")
            st.divider()
        
        # Add new subscriber
        with st.expander("➕ Add New Subscriber", expanded=True):
            # Initialize session state for preferences
            if "subscriber_preferences_json" not in st.session_state:
                st.session_state.subscriber_preferences_json = '''{
    "frequency": "daily",
    "alert_types": ["price_drop", "back_in_stock"],
    "quiet_hours": {
        "start": "22:00",
        "end": "08:00"
    },
    "max_alerts_per_day": 5
}'''
            
            # Quick preset buttons (outside form)
            st.markdown("**Quick Presets:**")
            col_preset1, col_preset2, col_preset3 = st.columns(3)
            with col_preset1:
                if st.button("📧 Daily Alerts", help="Daily frequency with all alert types", key="preset_daily"):
                    st.session_state.subscriber_preferences_json = '''{
    "frequency": "daily",
    "alert_types": ["price_drop", "back_in_stock", "threshold_breach", "historical_low"],
    "quiet_hours": {
        "start": "22:00",
        "end": "08:00"
    },
    "max_alerts_per_day": 10
}'''
                    st.rerun()
            with col_preset2:
                if st.button("📊 Weekly Summary", help="Weekly frequency with price drops only", key="preset_weekly"):
                    st.session_state.subscriber_preferences_json = '''{
    "frequency": "weekly",
    "alert_types": ["price_drop"],
    "quiet_hours": {
        "start": "22:00",
        "end": "08:00"
    },
    "max_alerts_per_day": 2
}'''
                    st.rerun()
            with col_preset3:
                if st.button("🚨 Urgent Only", help="Immediate alerts for threshold breaches only", key="preset_urgent"):
                    st.session_state.subscriber_preferences_json = '''{
    "frequency": "immediate",
    "alert_types": ["threshold_breach"],
    "quiet_hours": {
        "start": "23:00",
        "end": "07:00"
    },
    "max_alerts_per_day": 3
}'''
                    st.rerun()
            
            with st.form("add_subscriber"):
                col1, col2 = st.columns(2)
                with col1:
                    email = st.text_input("Email Address", placeholder="user@example.com")
                with col2:
                    name = st.text_input("Name (Optional)", placeholder="John Doe")
                
                # JSON preferences with session state
                preferences_text = st.text_area(
                    "Preferences (JSON)", 
                    value=st.session_state.subscriber_preferences_json,
                    key="subscriber_preferences_textarea",
                    help="JSON format for email preferences. Valid alert_types: price_drop, back_in_stock, threshold_breach, historical_low"
                )
                
                # Validate JSON
                try:
                    import json
                    preferences_dict = json.loads(preferences_text)
                    st.success("✅ Valid JSON format")
                    preferences = preferences_text
                except json.JSONDecodeError as e:
                    st.error(f"❌ Invalid JSON format: {e}")
                    st.info("Using default preferences")
                    default_preferences = {
                        "frequency": "daily",
                        "alert_types": ["price_drop", "back_in_stock"],
                        "quiet_hours": {"start": "22:00", "end": "08:00"},
                        "max_alerts_per_day": 5
                    }
                    preferences = json.dumps(default_preferences)
                
                if st.form_submit_button("Add Subscriber"):
                    if email and "@" in email:
                        try:
                            # Check if email already exists
                            existing_subscribers = db.get_email_subscribers(active_only=False)
                            if any(sub.email.lower() == email.lower() for sub in existing_subscribers):
                                st.error(f"❌ Email subscriber {email} already exists!")
                            else:
                                db.add_email_subscriber(email, name, preferences)
                                st.success(f"✅ Added subscriber: {email}")
                                
                                # Send welcome email to new subscriber
                                try:
                                    send_welcome_email(email, name, db)
                                    st.success("📧 Welcome email sent!")
                                except Exception as email_error:
                                    st.warning(f"⚠️ Subscriber added but welcome email failed: {email_error}")
                                
                                st.rerun()
                        except Exception as e:
                            if "UNIQUE constraint failed" in str(e):
                                st.error(f"❌ Email subscriber {email} already exists!")
                            else:
                                st.error(f"❌ Failed to add subscriber: {e}")
                    else:
                        st.error("Please enter a valid email address")
        
        # List subscribers
        st.markdown("#### 📋 Current Subscribers")
        subscribers = db.get_email_subscribers(active_only=False)
        
        if subscribers:
            for sub in subscribers:
                col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
                with col1:
                    st.write(f"📧 {sub.email}")
                    if sub.name:
                        st.caption(f"👤 {sub.name}")
                with col2:
                    status = "✅ Active" if sub.is_active else "❌ Inactive"
                    st.write(status)
                with col3:
                    if st.button("✏️", key=f"edit_{sub.id}"):
                        st.session_state[f"edit_sub_{sub.id}"] = True
                with col4:
                    if st.button("🗑️", key=f"delete_{sub.id}"):
                        if st.session_state.get(f"confirm_delete_{sub.id}", False):
                            db.delete_email_subscriber(sub.id)
                            st.success("Subscriber deleted!")
                            st.rerun()
                        else:
                            st.session_state[f"confirm_delete_{sub.id}"] = True
                            st.warning("Click again to confirm deletion")
                
                # Edit form
                if st.session_state.get(f"edit_sub_{sub.id}", False):
                    with st.form(f"edit_subscriber_{sub.id}"):
                        new_email = st.text_input("Email", value=sub.email)
                        new_name = st.text_input("Name", value=sub.name or "")
                        new_preferences = st.text_area("Preferences", value=sub.preferences)
                        new_active = st.checkbox("Active", value=sub.is_active)
                        
                        col_save, col_cancel = st.columns(2)
                        with col_save:
                            if st.form_submit_button("💾 Save"):
                                db.update_email_subscriber(
                                    sub.id,
                                    email=new_email,
                                    name=new_name,
                                    preferences=new_preferences,
                                    is_active=new_active
                                )
                                del st.session_state[f"edit_sub_{sub.id}"]
                                st.success("Subscriber updated!")
                                st.rerun()
                        with col_cancel:
                            if st.form_submit_button("❌ Cancel"):
                                del st.session_state[f"edit_sub_{sub.id}"]
                                st.rerun()
                
                st.divider()
        else:
            st.info("No subscribers found. Add your first subscriber above!")
    
    with tab3:
        st.markdown("#### ⏰ Alert Schedules")
        
        # Add new schedule
        with st.expander("➕ Add New Schedule", expanded=True):
            with st.form("add_schedule"):
                name = st.text_input("Schedule Name", placeholder="Daily Price Check")
                frequency = st.number_input("Frequency (hours)", min_value=1, max_value=168, value=24, help="How often to send alerts (1-168 hours)")
                
                if st.form_submit_button("Add Schedule"):
                    try:
                        db.add_alert_schedule(name, frequency)
                        st.success(f"✅ Added schedule: {name}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Failed to add schedule: {e}")
        
        # List schedules
        st.markdown("#### 📋 Current Schedules")
        schedules = db.get_alert_schedules(active_only=False)
        
        if schedules:
            for schedule in schedules:
                col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
                with col1:
                    st.write(f"⏰ {schedule.name}")
                    st.caption(f"Every {schedule.frequency_hours} hours")
                with col2:
                    status = "✅ Active" if schedule.is_active else "❌ Inactive"
                    st.write(status)
                with col3:
                    if st.button("✏️", key=f"edit_schedule_{schedule.id}"):
                        st.session_state[f"edit_schedule_{schedule.id}"] = True
                with col4:
                    if st.button("🗑️", key=f"delete_schedule_{schedule.id}"):
                        if st.session_state.get(f"confirm_delete_schedule_{schedule.id}", False):
                            db.delete_alert_schedule(schedule.id)
                            st.success("Schedule deleted!")
                            st.rerun()
                        else:
                            st.session_state[f"confirm_delete_schedule_{schedule.id}"] = True
                            st.warning("Click again to confirm deletion")
                
                # Edit form
                if st.session_state.get(f"edit_schedule_{schedule.id}", False):
                    with st.form(f"edit_schedule_{schedule.id}"):
                        new_name = st.text_input("Name", value=schedule.name)
                        new_frequency = st.number_input("Frequency (hours)", value=int(schedule.frequency_hours), min_value=1, max_value=168)
                        new_active = st.checkbox("Active", value=schedule.is_active)
                        
                        col_save, col_cancel = st.columns(2)
                        with col_save:
                            if st.form_submit_button("💾 Save"):
                                db.update_alert_schedule(
                                    schedule.id,
                                    name=new_name,
                                    frequency_hours=new_frequency,
                                    is_active=new_active
                                )
                                del st.session_state[f"edit_schedule_{schedule.id}"]
                                st.success("Schedule updated!")
                                st.rerun()
                        with col_cancel:
                            if st.form_submit_button("❌ Cancel"):
                                del st.session_state[f"edit_schedule_{schedule.id}"]
                                st.rerun()
                
                st.divider()
        else:
            st.info("No schedules found. Add your first schedule above!")
    
    with tab4:
        st.markdown("#### 📧 Gmail Accounts Management")
        
        # Show existing Gmail accounts
        existing_gmail_accounts = db.get_gmail_accounts(active_only=False)
        if existing_gmail_accounts:
            st.markdown("#### 📋 Existing Gmail Accounts")
            for account in existing_gmail_accounts:
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.write(f"📧 **{account.email}**")
                    if account.name:
                        st.caption(f"👤 {account.name}")
                with col2:
                    if account.is_default:
                        st.success("⭐ Default")
                    else:
                        st.info("Secondary")
                with col3:
                    status = "✅ Active" if account.is_active else "❌ Inactive"
                    st.write(status)
            st.divider()
        
        # Add new Gmail account
        with st.expander("➕ Add New Gmail Account", expanded=True):
            with st.form("add_gmail_account"):
                col1, col2 = st.columns(2)
                with col1:
                    gmail_email = st.text_input("Gmail Address", placeholder="your.email@gmail.com")
                with col2:
                    gmail_name = st.text_input("Account Name (Optional)", placeholder="Personal Gmail")
                
                gmail_password = st.text_input("App Password", type="password", placeholder="16-character app password")
                is_default = st.checkbox("Set as Default Account", help="This will be used for sending emails")
                
                col_test, col_add = st.columns(2)
                with col_test:
                    if st.form_submit_button("🧪 Test Account"):
                        if gmail_email and gmail_password:
                            with st.spinner("Testing Gmail account..."):
                                if db.test_gmail_account(gmail_email, gmail_password):
                                    st.success("✅ Gmail account test successful!")
                                else:
                                    st.error("❌ Gmail account test failed. Check your credentials.")
                        else:
                            st.error("Please enter both email and app password")
                
                with col_add:
                    if st.form_submit_button("Add Gmail Account"):
                        if gmail_email and gmail_password and "@" in gmail_email:
                            try:
                                # Check if email already exists
                                existing_accounts = db.get_gmail_accounts(active_only=False)
                                if any(acc.email.lower() == gmail_email.lower() for acc in existing_accounts):
                                    st.error(f"❌ Gmail account {gmail_email} already exists!")
                                else:
                                    db.add_gmail_account(gmail_email, gmail_password, gmail_name, is_default)
                                    st.success(f"✅ Added Gmail account: {gmail_email}")
                                    st.rerun()
                            except Exception as e:
                                if "UNIQUE constraint failed" in str(e):
                                    st.error(f"❌ Gmail account {gmail_email} already exists!")
                                else:
                                    st.error(f"❌ Failed to add Gmail account: {e}")
                        else:
                            st.error("Please enter a valid Gmail address and app password")
        
        # List Gmail accounts
        st.markdown("#### 📋 Current Gmail Accounts")
        gmail_accounts = db.get_gmail_accounts(active_only=False)
        
        if gmail_accounts:
            for account in gmail_accounts:
                col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 1])
                with col1:
                    st.write(f"📧 {account.email}")
                    if account.name:
                        st.caption(f"👤 {account.name}")
                    if account.is_default:
                        st.caption("⭐ Default Account")
                with col2:
                    status = "✅ Active" if account.is_active else "❌ Inactive"
                    st.write(status)
                with col3:
                    if st.button("🧪", key=f"test_{account.id}", help="Test Account"):
                        with st.spinner("Testing..."):
                            if db.test_gmail_account(account.email, account.app_password):
                                st.success("✅ Test successful!")
                            else:
                                st.error("❌ Test failed!")
                with col4:
                    if st.button("✏️", key=f"edit_gmail_{account.id}"):
                        st.session_state[f"edit_gmail_{account.id}"] = True
                with col5:
                    if st.button("🗑️", key=f"delete_gmail_{account.id}"):
                        if st.session_state.get(f"confirm_delete_gmail_{account.id}", False):
                            db.delete_gmail_account(account.id)
                            st.success("Gmail account deleted!")
                            st.rerun()
                        else:
                            st.session_state[f"confirm_delete_gmail_{account.id}"] = True
                            st.warning("Click again to confirm deletion")
                
                # Edit form
                if st.session_state.get(f"edit_gmail_{account.id}", False):
                    with st.form(f"edit_gmail_{account.id}"):
                        new_email = st.text_input("Email", value=account.email)
                        new_name = st.text_input("Name", value=account.name or "")
                        new_password = st.text_input("App Password", type="password", value=account.app_password)
                        new_active = st.checkbox("Active", value=account.is_active)
                        new_default = st.checkbox("Default Account", value=account.is_default)
                        
                        col_save, col_cancel = st.columns(2)
                        with col_save:
                            if st.form_submit_button("💾 Save"):
                                db.update_gmail_account(
                                    account.id,
                                    email=new_email,
                                    name=new_name,
                                    app_password=new_password,
                                    is_active=new_active,
                                    is_default=new_default
                                )
                                del st.session_state[f"edit_gmail_{account.id}"]
                                st.success("Gmail account updated!")
                                st.rerun()
                        with col_cancel:
                            if st.form_submit_button("❌ Cancel"):
                                del st.session_state[f"edit_gmail_{account.id}"]
                                st.rerun()
                
                st.divider()
        else:
            st.info("No Gmail accounts found. Add your first Gmail account above!")
    
    with tab5:
        st.markdown("#### 📧 Gmail Configuration")
        
        st.markdown("""
        ### 🔧 How to Set Up Gmail for Price Tracker
        
        **Step 1: Enable 2-Factor Authentication**
        1. Go to [Google Account Settings](https://myaccount.google.com/)
        2. Click on "Security" in the left sidebar
        3. Enable "2-Step Verification" if not already enabled
        
        **Step 2: Generate App Password**
        1. In Google Account Settings, go to "Security"
        2. Under "2-Step Verification", click "App passwords"
        3. Select "Mail" and "Other (Custom name)"
        4. Enter "Price Tracker" as the name
        5. Copy the generated 16-character password
        
        **Step 3: Configure in .env File**
        Create or edit the `.env` file in your project directory:
        ```env
        EMAIL_ADDRESS=your_email@gmail.com
        EMAIL_APP_PASSWORD=your_16_character_app_password
        ADMIN_EMAIL=your_email@gmail.com
        ```
        
        **Step 4: Test Configuration**
        Use the test button below to verify your settings work.
        """)
        
        # Test email configuration
        if st.button("🧪 Test Email Configuration"):
            try:
                from alerts.email_handler import EmailHandler, EmailConfig
                
                # Get default Gmail account from database
                default_account = db.get_default_gmail_account()
                if not default_account:
                    st.error("❌ No default Gmail account configured")
                    st.error("Please add a Gmail account in the 'Gmail Accounts' tab and set it as default")
                else:
                    email_config = EmailConfig(
                        address=default_account.email,
                        app_password=default_account.app_password,
                        admin_email=default_account.email,
                        quiet_start="22:00",
                        quiet_end="08:00"
                    )
                    
                    email_handler = EmailHandler(email_config)
                    
                    # Send test email
                    test_subscribers = db.get_email_subscribers(active_only=True)
                    if test_subscribers:
                        test_emails = [sub.email for sub in test_subscribers[:1]]  # Test with first subscriber
                    else:
                        test_emails = [default_account.email]  # Test with Gmail account
                    
                    email_handler.send_alert(
                        to_emails=test_emails,
                        subject="🧪 Price Tracker Test Email",
                        product={
                            "name": "Test Product",
                            "current_price": 999.99,
                            "original_price": 1299.99,
                            "discount_percent": 23.1,
                            "website": "Test Store",
                            "url": "https://example.com",
                            "availability": True
                        },
                        history_df=pd.DataFrame({
                            "timestamp": ["2024-01-01", "2024-01-02"],
                            "price": [1299.99, 999.99]
                        }),
                        alert_message="This is a test email from Price Tracker!",
                        buy_url="https://example.com"
                    )
                    
                    st.success("✅ Test email sent successfully!")
                    st.success(f"📧 Sent to: {', '.join(test_emails)}")
            except Exception as e:
                st.error(f"❌ Test failed: {e}")
                st.error("Please check your Gmail configuration in the .env file")
    
    with tab5:
        st.markdown("#### 📊 Email Statistics")
        
        # Get stats
        subscribers = db.get_email_subscribers(active_only=False)
        active_subscribers = len([s for s in subscribers if s.is_active])
        schedules = db.get_alert_schedules(active_only=False)
        active_schedules = len([s for s in schedules if s.is_active])
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Subscribers", len(subscribers))
        with col2:
            st.metric("Active Subscribers", active_subscribers)
        with col3:
            st.metric("Total Schedules", len(schedules))
        with col4:
            st.metric("Active Schedules", active_schedules)
        
        # Email configuration status
        st.markdown("#### 🔧 Configuration Status")
        email_address = os.getenv("EMAIL_ADDRESS", "")
        email_password = os.getenv("EMAIL_APP_PASSWORD", "")
        
        col1, col2 = st.columns(2)
        with col1:
            if email_address:
                st.success("✅ Email address configured")
            else:
                st.error("❌ Email address not configured")
        
        with col2:
            if email_password:
                st.success("✅ App password configured")
            else:
                st.error("❌ App password not configured")
        
        # Recent activity
        st.markdown("#### 📈 Recent Activity")
        st.info("Email activity tracking will be implemented in future updates.")
    
    with tab6:
        st.markdown("#### 📊 Email Statistics")
        
        # Subscriber statistics
        st.markdown("#### 👥 Subscriber Statistics")
        subscribers = db.get_email_subscribers(active_only=False)
        active_subscribers = db.get_email_subscribers(active_only=True)
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Subscribers", len(subscribers))
        with col2:
            st.metric("Active Subscribers", len(active_subscribers))
        with col3:
            st.metric("Inactive Subscribers", len(subscribers) - len(active_subscribers))
        with col4:
            if subscribers:
                st.metric("Active Rate", f"{(len(active_subscribers)/len(subscribers)*100):.1f}%")
            else:
                st.metric("Active Rate", "0%")
        
        # Gmail account statistics
        st.markdown("#### 📧 Gmail Account Statistics")
        gmail_accounts = db.get_gmail_accounts(active_only=False)
        active_gmail_accounts = db.get_gmail_accounts(active_only=True)
        default_account = db.get_default_gmail_account()
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Gmail Accounts", len(gmail_accounts))
        with col2:
            st.metric("Active Gmail Accounts", len(active_gmail_accounts))
        with col3:
            st.metric("Inactive Gmail Accounts", len(gmail_accounts) - len(active_gmail_accounts))
        with col4:
            if default_account:
                st.metric("Default Account", "✅ Set")
            else:
                st.metric("Default Account", "❌ Not Set")
        
        # Configuration status
        st.markdown("#### ⚙️ Configuration Status")
        
        col1, col2 = st.columns(2)
        with col1:
            if gmail_accounts:
                st.success(f"✅ {len(gmail_accounts)} Gmail account(s) configured")
                if default_account:
                    st.success(f"✅ Default account: {default_account.email}")
                else:
                    st.warning("⚠️ No default Gmail account set")
            else:
                st.error("❌ No Gmail accounts configured")
        
        with col2:
            if os.getenv("EMAIL_ADDRESS") and os.getenv("EMAIL_APP_PASSWORD"):
                st.info("ℹ️ Environment variables also configured")
            else:
                st.info("ℹ️ Using database Gmail accounts only")
        
        # Gmail account details
        if gmail_accounts:
            st.markdown("#### 📧 Gmail Account Details")
            for account in gmail_accounts:
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    st.write(f"📧 {account.email}")
                    if account.name:
                        st.caption(f"👤 {account.name}")
                with col2:
                    if account.is_default:
                        st.success("⭐ Default")
                    else:
                        st.info("Secondary")
                with col3:
                    if account.last_used:
                        st.caption(f"Last used: {account.last_used[:10]}")
                    else:
                        st.caption("Never used")
        
        # Alert schedule statistics
        st.markdown("#### ⏰ Alert Schedule Statistics")
        schedules = db.get_alert_schedules(active_only=False)
        active_schedules = db.get_alert_schedules(active_only=True)
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Schedules", len(schedules))
        with col2:
            st.metric("Active Schedules", len(active_schedules))
        with col3:
            st.metric("Inactive Schedules", len(schedules) - len(active_schedules))


def send_welcome_email(email: str, name: str, db: DatabaseManager) -> None:
    """Send welcome email to new subscriber."""
    try:
        from alerts.email_handler import EmailHandler, EmailConfig
        
        # Get default Gmail account from database
        default_account = db.get_default_gmail_account()
        if not default_account:
            raise Exception("No default Gmail account configured")
        
        email_config = EmailConfig(
            address=default_account.email,
            app_password=default_account.app_password,
            admin_email=default_account.email,
            quiet_start="22:00",
            quiet_end="08:00"
        )
        
        email_handler = EmailHandler(email_config)
        
        # Create welcome email content
        welcome_product = {
            "name": "Welcome to Price Tracker!",
            "current_price": 0.00,
            "original_price": 0.00,
            "discount_percent": 0.0,
            "website": "Price Tracker",
            "url": "https://github.com/your-repo/price-tracker",
            "availability": True
        }
        
        welcome_message = f"Welcome {name or 'to Price Tracker'}! You'll now receive alerts when products you're tracking have price changes."
        
        email_handler.send_alert(
            to_emails=[email],
            subject="🎉 Welcome to Price Tracker!",
            product=welcome_product,
            history_df=pd.DataFrame({
                "timestamp": ["2024-01-01"],
                "price": [0.00]
            }),
            alert_message=welcome_message,
            buy_url="https://github.com/your-repo/price-tracker"
        )
        
        # Update last used timestamp
        db.update_gmail_account(default_account.id, last_used=datetime.now().isoformat())
        
    except Exception as e:
        logger.error(f"Failed to send welcome email: {e}")
        raise


def send_alert_to_subscribers(product_data: dict, alert_message: str, db: DatabaseManager) -> None:
    """Send price alert to all active subscribers."""
    try:
        from alerts.email_handler import EmailHandler, EmailConfig
        
        # Get default Gmail account from database
        default_account = db.get_default_gmail_account()
        if not default_account:
            logger.warning("No default Gmail account configured, skipping email alerts")
            return
        
        email_config = EmailConfig(
            address=default_account.email,
            app_password=default_account.app_password,
            admin_email=default_account.email,
            quiet_start="22:00",
            quiet_end="08:00"
        )
        
        # Get active subscribers
        subscribers = db.get_email_subscribers(active_only=True)
        if not subscribers:
            logger.info("No active subscribers found")
            return
        
        email_handler = EmailHandler(email_config)
        subscriber_emails = [sub.email for sub in subscribers]
        
        # Get price history for the product
        price_history = db.list_price_history(product_data.get('id'))
        if price_history:
            history_df = pd.DataFrame([dict(ph) for ph in price_history])
            history_df['timestamp'] = pd.to_datetime(history_df['timestamp'])
        else:
            history_df = pd.DataFrame({
                "timestamp": [pd.Timestamp.now()],
                "price": [product_data.get('current_price', 0)]
            })
        
        # Send alert to all subscribers
        email_handler.send_alert(
            to_emails=subscriber_emails,
            subject=f"🚨 Price Alert: {product_data.get('name', 'Product')}",
            product=product_data,
            history_df=history_df,
            alert_message=alert_message,
            buy_url=product_data.get('url', '')
        )
        
        # Update last used timestamp
        db.update_gmail_account(default_account.id, last_used=datetime.now().isoformat())
        
        logger.info(f"Price alert sent to {len(subscriber_emails)} subscribers")
        
    except Exception as e:
        logger.error(f"Failed to send alert to subscribers: {e}")


def main() -> None:
    load_dotenv()
    ensure_dirs()
    cfg = get_config()
    db = get_db(cfg["database"]["path"], cfg["database"]["pool_size"])
    seed_demo(db)
    
    # Check if analytics was clicked from dashboard
    if hasattr(st.session_state, 'analytics_clicked') and st.session_state.analytics_clicked:
        # Clear the flag and render analytics
        del st.session_state.analytics_clicked
        render_analytics(cfg, db)
        return
    
    # Check if back to dashboard was clicked
    if hasattr(st.session_state, 'back_to_dashboard') and st.session_state.back_to_dashboard:
        # Clear the flag and render dashboard
        del st.session_state.back_to_dashboard
        render_dashboard(cfg, db)
        return
    
    # Get page from sidebar
    page = sidebar(cfg, db)
    
    # Handle navigation
    if page == "Dashboard":
        render_dashboard(cfg, db)
    elif page == "Add Products":
        render_add_products(cfg, db)
    elif page == "Analytics":
        render_analytics(cfg, db)
    elif page == "Websites":
        render_websites(cfg, db)
    elif page == "Settings":
        render_settings(cfg, db)
    else:
        render_alert_history(cfg, db)


if __name__ == "__main__":
    main()


