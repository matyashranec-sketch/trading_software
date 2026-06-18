"""Background jobs: daily predictions + hourly evaluation sweep."""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.db import session_scope
from app.engine.evaluator import run_evaluations
from app.engine.predictor import run_predictions

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _prediction_job() -> None:
    try:
        with session_scope() as session:
            summary = run_predictions(session)
        logger.info("Scheduled predictions: %s", summary)
    except Exception:
        logger.exception("Prediction job failed")


def _evaluation_job() -> None:
    try:
        with session_scope() as session:
            summary = run_evaluations(session)
        logger.info("Scheduled evaluations: %s", summary)
    except Exception:
        logger.exception("Evaluation job failed")


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    settings = get_settings()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _prediction_job,
        CronTrigger(hour=settings.prediction_hour, minute=0),
        id="predictions",
        replace_existing=True,
    )
    scheduler.add_job(
        _evaluation_job,
        IntervalTrigger(minutes=settings.evaluation_interval_minutes),
        id="evaluations",
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Scheduler started (predictions %02d:00 UTC, evaluations every %d min).",
        settings.prediction_hour,
        settings.evaluation_interval_minutes,
    )
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
