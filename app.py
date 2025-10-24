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
                        'Snapdeal': '📦'
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
                'Snapdeal': '📦'
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
                    new_threshold = st.number_input("Price Threshold (₹)", value=row.get('user_threshold') or 0, min_value=0)
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
        user_threshold = st.number_input("Default price threshold (₹)", min_value=0, value=0)
    
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
            with st.spinner("Scraping product details..."):
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
                            placeholder="https://www.amazon.in/dp/B0CHX2Z5H3")
    
    if st.button("Preview Scrape") and demo_url:
        if not is_valid_url(demo_url):
            st.error("Invalid URL format.")
            return
            
        with st.spinner("Scraping product details..."):
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
        
        if data:
            st.success("✅ Scraping successful!")
            
            # Display scraped data in a nice format
            product_data = data[0]
            
            col1, col2 = st.columns([1, 1])
            with col1:
                if product_data.get("image_url"):
                    st.image(product_data["image_url"], width=200)
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
            st.error("❌ Scraping failed. The website might be blocking requests or the URL might be invalid.")


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
            st.experimental_rerun()


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
        'Snapdeal': '📦'
    }
    icon = website_icons.get(selected_website, '🌐')
    st.markdown(f"### {icon} {selected_website} Products")
    
    # Display products for this website
    for _, row in website_products.iterrows():
        render_product_card(row, db, is_list=True)

def render_alert_history(cfg: dict, db: DatabaseManager) -> None:
    st.markdown("### 📬 Alert History")
    
    # Get alerts from database
    alerts = db.list_alerts()
    
    if not alerts:
        st.info("No alerts generated yet. Alerts will appear here when price thresholds are met.")
        return
    
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


