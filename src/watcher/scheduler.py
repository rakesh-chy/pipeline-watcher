"""APScheduler-based evaluator loop."""

from __future__ import annotations

import logging
import time

from apscheduler.schedulers.background import BackgroundScheduler

from watcher.alerter import Alerter
from watcher.config import get_settings
from watcher.runner import evaluate_once
from watcher.storage import Storage

logger = logging.getLogger(__name__)


def run_forever() -> None:
    settings = get_settings()
    storage = Storage(settings=settings)
    alerter = Alerter(settings=settings)
    scheduler = BackgroundScheduler(timezone="UTC")

    def tick() -> None:
        try:
            summary = evaluate_once(storage, alerter=alerter)
            logger.info(
                "tick: %d pipelines, %d opened, %d resolved",
                summary.pipelines_checked,
                summary.incidents_opened,
                summary.incidents_resolved,
            )
        except Exception:
            logger.exception("evaluator tick failed")

    scheduler.add_job(tick, "interval", seconds=settings.check_interval_seconds, next_run_time=None)
    tick()
    scheduler.start()
    logger.info("scheduler started (every %ds)", settings.check_interval_seconds)
    try:
        while True:
            time.sleep(1)
    finally:
        scheduler.shutdown()
        storage.close()
        alerter.close()
