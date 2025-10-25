from __future__ import annotations

import base64
import io
import os
from dataclasses import dataclass
from datetime import datetime, time
from typing import Dict, List, Optional

import pandas as pd
import plotly.express as px
import yagmail
from jinja2 import Environment, FileSystemLoader, select_autoescape
from loguru import logger


@dataclass
class EmailConfig:
    address: str
    app_password: str
    admin_email: str
    quiet_start: str
    quiet_end: str


def is_quiet_hours(start: str, end: str, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    s_h, s_m = map(int, start.split(":"))
    e_h, e_m = map(int, end.split(":"))
    start_t = time(s_h, s_m)
    end_t = time(e_h, e_m)
    if start_t < end_t:
        return start_t <= now.time() <= end_t
    # wraps midnight
    return now.time() >= start_t or now.time() <= end_t


class EmailHandler:
    def __init__(self, cfg: EmailConfig) -> None:
        self.cfg = cfg
        self.yag = yagmail.SMTP(cfg.address, cfg.app_password)
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        self.env = Environment(
            loader=FileSystemLoader(template_dir), autoescape=select_autoescape(["html", "xml"])
        )

    def _render_chart_inline(self, history_df: pd.DataFrame) -> str:
        fig = px.line(history_df, x="timestamp", y="price", height=200, title="Price Trend")
        fig.update_layout(margin=dict(l=0, r=0, t=30, b=0))
        buf = io.BytesIO()
        fig.write_image(buf, format="png")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"

    def send_alert(
        self,
        to_emails: List[str],
        subject: str,
        product: Dict[str, any],
        history_df: pd.DataFrame,
        alert_message: str,
        buy_url: str,
    ) -> None:
        """Send alert to multiple email addresses."""
        if is_quiet_hours(self.cfg.quiet_start, self.cfg.quiet_end):
            logger.info("Quiet hours active; skipping immediate email.")
            return
        
        try:
            chart_uri = self._render_chart_inline(history_df)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Failed to render chart: {exc}")
            chart_uri = ""

        template = self.env.get_template("alert_email.html")
        html = template.render(product=product, alert_message=alert_message, chart_uri=chart_uri, buy_url=buy_url)
        
        # Send to all email addresses
        for email in to_emails:
            try:
                self.yag.send(to=email, subject=subject, contents=html)
                logger.info(f"Alert sent successfully to {email}")
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Email send failed to {email}: {exc}")

    def send_bulk_alert(
        self,
        subject: str,
        products: List[Dict[str, any]],
        alert_message: str,
        to_emails: List[str],
    ) -> None:
        """Send bulk alert for multiple products."""
        if is_quiet_hours(self.cfg.quiet_start, self.cfg.quiet_end):
            logger.info("Quiet hours active; skipping bulk email.")
            return
        
        template = self.env.get_template("bulk_alert_email.html")
        html = template.render(products=products, alert_message=alert_message)
        
        for email in to_emails:
            try:
                self.yag.send(to=email, subject=subject, contents=html)
                logger.info(f"Bulk alert sent successfully to {email}")
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Bulk email send failed to {email}: {exc}")

    def send_digest(
        self,
        to_emails: List[str],
        subject: str,
        products: List[Dict[str, any]],
        digest_data: Dict[str, any],
    ) -> None:
        """Send daily/weekly digest to subscribers."""
        template = self.env.get_template("digest_email.html")
        html = template.render(products=products, digest_data=digest_data)
        
        for email in to_emails:
            try:
                self.yag.send(to=email, subject=subject, contents=html)
                logger.info(f"Digest sent successfully to {email}")
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Digest email send failed to {email}: {exc}")


