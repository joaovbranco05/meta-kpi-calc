"""Explicit Lead Ads commands. Network use is opt-in, never an API lifecycle task."""

import argparse
import json
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.core.logging import configure_logging
from meta_kpi_calc.crm.inbox import utcnow
from meta_kpi_calc.crm.inbox_models import ReconciliationState, WebhookEvent
from meta_kpi_calc.crm.lead_ads_client import LeadAdsError, MetaLeadAdsClient
from meta_kpi_calc.crm.processing import fetch_single_lead, process_events
from meta_kpi_calc.crm.reconciliation import reconcile_form
from meta_kpi_calc.db.session import Database


def _summary(factory) -> dict:
    with factory() as session:
        states = dict(session.execute(select(WebhookEvent.status, func.count()).group_by(WebhookEvent.status)).all())
        pending = session.scalar(select(func.min(WebhookEvent.received_at)).where(WebhookEvent.status.in_(("PENDING", "RETRY", "PROCESSING"))))
        last = session.scalar(select(func.max(ReconciliationState.last_success_at)))
        attempts = session.scalar(select(func.coalesce(func.sum(WebhookEvent.attempts), 0)))
        reconciliation = dict(session.execute(select(ReconciliationState.last_result, func.count()).group_by(ReconciliationState.last_result)).all())
    from datetime import timezone
    if pending is not None:
        pending = pending.replace(tzinfo=timezone.utc) if pending.tzinfo is None else pending.astimezone(timezone.utc)
    age = max(0, int((utcnow() - pending).total_seconds())) if pending else None
    return {"events": states, "attempts_total": attempts, "reconciliation_results": reconciliation,
            "oldest_pending_seconds": age, "last_reconciliation_at": last.isoformat() if last else None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local Lead Ads technical commands; network requires explicit opt-in.")
    parser.add_argument("command", choices=("status", "process", "worker", "reconcile", "fetch-lead"))
    parser.add_argument("--database-url", help="Database URL; worker defaults to the configured active database.")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--max-events", type=int, default=100)
    parser.add_argument("--lead-id", help="Single lead ID required by fetch-lead.")
    parser.add_argument("--form-id")
    parser.add_argument("--start", help="UTC/offset ISO timestamp; required for first reconciliation.")
    parser.add_argument("--end", help="UTC/offset ISO timestamp; defaults to captured start of scan.")
    args = parser.parse_args(argv)
    database = None
    try:
        configured = Settings()
        if not args.database_url and args.command != "worker":
            raise LeadAdsError("database_unavailable")
        url = make_url(args.database_url or configured.active_database_url)
        if url.drivername not in {"sqlite", "postgresql", "postgresql+psycopg"} or not url.database or url.database == ":memory:":
            raise LeadAdsError("database_unavailable")
        if url.drivername == "sqlite":
            database_path = Path(url.database).resolve()
            if not database_path.is_file():
                raise LeadAdsError("database_unavailable")
            database_url = URL.create("sqlite", database=str(database_path)).render_as_string(hide_password=False)
        else:
            if not url.host:
                raise LeadAdsError("database_unavailable")
            database_url = url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
        if args.command != "status" and (not args.allow_network or configured.demo_mode or not configured.lead_ads_graph_ready):
            raise LeadAdsError("network_not_authorized")
        if not 1 <= args.max_events <= 10000:
            raise LeadAdsError("configuration_invalid")
        settings = configured.model_copy(update={"database_url": database_url,
            "demo_database_url": "sqlite:///:memory:", "demo_mode": False})
        configure_logging(settings)
        database = Database(settings)
        if args.command == "status":
            result = _summary(database.session_factory)
        else:
            with httpx.Client(follow_redirects=False) as http:
                client = MetaLeadAdsClient(http, token=settings.lead_ads_access_token.get_secret_value(),
                                          api_version=settings.lead_ads_api_version,
                                          max_pages=settings.lead_ads_max_pages, page_size=settings.lead_ads_page_size)
                if args.command == "worker":
                    from meta_kpi_calc.crm.continuous_worker import run_with_signals
                    run_with_signals(database.session_factory, client, settings)
                    return 0
                if args.command == "process":
                    result = process_events(database.session_factory, client, settings, max_events=args.max_events)
                elif args.command == "reconcile":
                    if not args.form_id:
                        raise LeadAdsError("source_not_allowed")
                    result = reconcile_form(database.session_factory, client, settings, form_id=args.form_id,
                                            start=datetime.fromisoformat(args.start.replace("Z", "+00:00")) if args.start else None,
                                            end=datetime.fromisoformat(args.end.replace("Z", "+00:00")) if args.end else None)
                else:
                    if not args.lead_id:
                        raise LeadAdsError("lead_id_required")
                    result = fetch_single_lead(database.session_factory, client, settings, lead_id=args.lead_id)
        print(json.dumps(result, sort_keys=True))
        return 0
    except LeadAdsError as error:
        print(json.dumps({"error": error.code}))
        return 2
    except (SQLAlchemyError, OSError, ValueError):
        print(json.dumps({"error": "operation_failed"}))
        return 2
    finally:
        if database is not None:
            database.engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
