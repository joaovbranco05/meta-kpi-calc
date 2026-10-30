"""Opt-in polling loop around the durable one-shot inbox processor."""

import json
import logging
import signal
from datetime import datetime, timezone
from threading import Event

from sqlalchemy import func, select

from meta_kpi_calc.crm.inbox_models import WebhookEvent
from meta_kpi_calc.crm.processing import process_events

logger = logging.getLogger(__name__)


def run_worker(factory, client, settings, *, stop: Event) -> None:
    """Run until stopped; each event retains the existing transactional lease fence."""
    processed = 0
    last_failure = None
    delay = settings.lead_ads_worker_backoff_base_seconds
    while not stop.is_set():
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            counts = process_events(factory, client, settings,
                                    max_events=settings.lead_ads_worker_batch_size,
                                    should_stop=stop.is_set)
            processed += counts["completed"]
            with factory() as session:
                backlog = session.scalar(select(func.count()).select_from(WebhookEvent).where(
                    WebhookEvent.status.in_(("PENDING", "RETRY", "PROCESSING"))))
            if counts["failed_or_retry"] or counts["lease_lost"]:
                last_failure = timestamp
            logger.info(json.dumps({"event": "worker_cycle", "timestamp": timestamp,
                                    "last_failure": last_failure, "processed_total": processed,
                                    "backlog": backlog, **counts}))
            delay = settings.lead_ads_worker_backoff_base_seconds
            stop.wait(settings.lead_ads_worker_poll_seconds)
        except Exception:
            # Exceptions can contain SQL parameters, request URLs, and credentials.
            last_failure = timestamp
            logger.error(json.dumps({"event": "worker_cycle_failed", "timestamp": timestamp,
                                     "error_code": "cycle_failed", "last_failure": last_failure,
                                     "processed_total": processed, "retry_seconds": delay}))
            stop.wait(delay)
            delay = min(settings.lead_ads_worker_backoff_max_seconds, delay * 2)
    logger.info(json.dumps({"event": "worker_stopped", "timestamp": datetime.now(timezone.utc).isoformat(),
                            "last_failure": last_failure, "processed_total": processed}))


def run_with_signals(factory, client, settings) -> None:
    stop = Event()
    previous = {}

    def request_stop(_signal, _frame):
        stop.set()

    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, request_stop)
        run_worker(factory, client, settings, stop=stop)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
