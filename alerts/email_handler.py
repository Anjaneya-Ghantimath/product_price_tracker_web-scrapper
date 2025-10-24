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
        to_email: str,
        subject: str,
        product: Dict[str, any],
        history_df: pd.DataFrame,
        alert_message: str,
        buy_url: str,
    ) -> None:
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
        try:
            self.yag.send(to=to_email, subject=subject, contents=html)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Email send failed: {exc}")


