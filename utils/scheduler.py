from __future__ import annotations

from datetime import datetime
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    return scheduler


def schedule_jobs(
    scheduler: BackgroundScheduler,
    scrape_job: Callable[[], None],
    cleanup_job: Callable[[], None],
    health_job: Callable[[], None],
    adaptive_hours: dict,
) -> None:
    # Health check hourly
    scheduler.add_job(health_job, "interval", minutes=60, id="health")
    # Cleanup daily
    scheduler.add_job(cleanup_job, "interval", hours=24, id="cleanup")
    # Initial scrape every 6 hours (adaptive logic can reschedule later)
    scheduler.add_job(scrape_job, "interval", hours=adaptive_hours.get("stable_hours", 6), id="scrape")
    logger.info("Scheduled jobs initialized")


