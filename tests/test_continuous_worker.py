"""Continuous worker tests use only synthetic data and mocked HTTP."""

import os
import signal
import subprocess
import sys
import time
from threading import Event

import httpx
import pytest
from sqlalchemy import func, select

from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.crm.continuous_worker import run_worker
from meta_kpi_calc.crm.inbox import EventInput, enqueue_events
from meta_kpi_calc.crm.inbox_models import WebhookEvent
from meta_kpi_calc.crm.models import Lead, LeadActivity
from test_lead_ads import graph, options, payload


class Steps:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.stopped = False
        self.delays = []

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.delays.append(seconds)
        action = next(self.actions, None)
        if action is None:
            self.stopped = True
        else:
            action()


def test_worker_empty_then_new_event_and_restart(migrated_database):
    settings, database = migrated_database
    settings = options(settings)
    def add():
        with database.session_factory.begin() as session:
            enqueue_events(session, [EventInput('30', '10', '20')])
    stop = Steps([add, None])
    run_worker(database.session_factory, graph(lambda _: httpx.Response(200, json=payload())), settings, stop=stop)
    assert len(stop.delays) == 2
    with database.session_factory() as session:
        assert session.scalar(select(WebhookEvent.status)) == 'COMPLETED'
        assert session.scalar(select(func.count(Lead.id))) == 1
    run_worker(database.session_factory, graph(lambda _: pytest.fail('duplicate fetch')), settings, stop=Steps([None]))
    with database.session_factory() as session:
        assert session.scalar(select(func.count(Lead.id))) == 1
        assert session.scalar(select(func.count(LeadActivity.id))) == 1


def test_worker_problem_event_does_not_block_next(migrated_database):
    settings, database = migrated_database
    settings = options(settings)
    with database.session_factory.begin() as session:
        enqueue_events(session, [EventInput('30', '10', '20'), EventInput('31', '10', '20')])
    def handler(request):
        return httpx.Response(503) if request.url.path.endswith('/30') else httpx.Response(200, json=payload('31'))
    run_worker(database.session_factory, graph(handler), settings, stop=Steps([None]))
    with database.session_factory() as session:
        assert set(session.scalars(select(WebhookEvent.status))) == {'RETRY', 'COMPLETED'}
        assert session.scalar(select(func.count(Lead.id))) == 1


def test_cycle_failure_backoff_and_safe_logs(migrated_database, monkeypatch, caplog):
    settings, database = migrated_database
    import meta_kpi_calc.crm.continuous_worker as module
    original = module.process_events
    count = 0
    def flaky(*args, **kwargs):
        nonlocal count
        count += 1
        if count <= 2:
            raise RuntimeError('secret-and-personal-data')
        return original(*args, **kwargs)
    monkeypatch.setattr(module, 'process_events', flaky)
    stop = Steps([lambda: None, lambda: None, None])
    run_worker(database.session_factory, graph(lambda _: pytest.fail('unexpected')), settings, stop=stop)
    assert stop.delays == [5, 10, 5]
    assert 'secret-and-personal-data' not in caplog.text


@pytest.mark.parametrize('field,value', [('lead_ads_worker_batch_size', 0), ('lead_ads_worker_poll_seconds', 0),
                                         ('lead_ads_worker_backoff_base_seconds', float('nan')),
                                         ('lead_ads_worker_backoff_max_seconds', 0)])
def test_invalid_config(field, value):
    with pytest.raises(ValueError) as err:
        Settings(_env_file=None, **{field: value})
    assert str(value) not in str(err.value) or value == 0


def test_invalid_backoff_relation():
    with pytest.raises(ValueError):
        Settings(_env_file=None, lead_ads_worker_backoff_base_seconds=10, lead_ads_worker_backoff_max_seconds=5)


@pytest.mark.parametrize('sig', [signal.SIGTERM, signal.SIGINT])
def test_real_signal_stops_during_wait(migrated_database, sig):
    settings, _ = migrated_database
    script = '''
import logging, sys
from meta_kpi_calc.core.config import Settings
from meta_kpi_calc.db.session import Database
from meta_kpi_calc.crm.continuous_worker import run_with_signals
logging.basicConfig(level=logging.INFO)
s = Settings(_env_file=None, database_url="sqlite:///unused.db", demo_database_url=sys.argv[1], lead_ads_worker_poll_seconds=60)
d = Database(s)
run_with_signals(d.session_factory, None, s)
d.engine.dispose()
'''
    proc = subprocess.Popen([sys.executable, '-u', '-c', script, settings.demo_database_url],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env={**os.environ, 'PYTHONPATH': 'src'})
    try:
        line = proc.stderr.readline()
        assert 'worker_cycle' in line
        proc.send_signal(sig)
        _, err = proc.communicate(timeout=5)
        assert proc.returncode == 0 and 'worker_stopped' in err
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()


def test_expired_lease_recovered_by_continuous_worker(migrated_database):
    from datetime import timedelta
    from meta_kpi_calc.crm.inbox import claim_event, utcnow
    from sqlalchemy import update
    settings, database = migrated_database
    settings = options(settings)
    with database.session_factory.begin() as session:
        enqueue_events(session, [EventInput('30', '10', '20')])
    with database.session_factory.begin() as session:
        assert claim_event(session, settings, utcnow()) is not None
        session.execute(update(WebhookEvent).values(lease_expires_at=utcnow() - timedelta(seconds=1)))
    run_worker(database.session_factory, graph(lambda _: httpx.Response(200, json=payload())), settings, stop=Steps([None]))
    with database.session_factory() as session:
        assert session.scalar(select(WebhookEvent.status)) == 'COMPLETED'
        assert session.scalar(select(WebhookEvent.attempts)) == 2
        assert session.scalar(select(func.count(Lead.id))) == 1


def test_two_workers_do_not_process_same_event(migrated_database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event as ThreadEvent
    settings, database = migrated_database
    settings = options(settings)
    with database.session_factory.begin() as session:
        enqueue_events(session, [EventInput('30', '10', '20')])
    entered, release = ThreadEvent(), ThreadEvent()
    calls = []
    def handler(_):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return httpx.Response(200, json=payload())
    client = graph(handler)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run_worker, database.session_factory, client, settings, stop=Steps([None]))
        try:
            assert entered.wait(5)
            second = pool.submit(run_worker, database.session_factory, client, settings, stop=Steps([None]))
            second.result(timeout=5)
        finally:
            release.set()
        first.result(timeout=5)
    assert len(calls) == 1
    with database.session_factory() as session:
        assert session.scalar(select(WebhookEvent.status)) == 'COMPLETED'
        assert session.scalar(select(func.count(Lead.id))) == 1


def test_stop_during_event_does_not_claim_next(migrated_database):
    settings, database = migrated_database
    settings = options(settings)
    with database.session_factory.begin() as session:
        enqueue_events(session, [EventInput('30', '10', '20'), EventInput('31', '10', '20')])
    stop = Event()
    def handler(_):
        stop.set()
        return httpx.Response(200, json=payload())
    run_worker(database.session_factory, graph(handler), settings, stop=stop)
    with database.session_factory() as session:
        assert set(session.scalars(select(WebhookEvent.status))) == {'PENDING', 'COMPLETED'}


def test_worker_requires_explicit_network_opt_in(monkeypatch, capsys, tmp_path):
    from meta_kpi_calc.crm import lead_ads_cli
    (tmp_path / 'synthetic.db').touch()
    configured = Settings(_env_file=None, demo_mode=False, lead_ads_enabled=True,
                          lead_ads_api_version='v26.0', lead_ads_access_token='synthetic-token',
                          database_url=f'sqlite:///{tmp_path / "synthetic.db"}')
    monkeypatch.setattr(lead_ads_cli, 'Settings', lambda: configured)
    assert lead_ads_cli.main(['worker']) == 2
    assert 'network_not_authorized' in capsys.readouterr().out


def test_invalid_config_cli_error_is_safe(monkeypatch, capsys):
    from meta_kpi_calc.crm import lead_ads_cli
    monkeypatch.setenv('LEAD_ADS_WORKER_POLL_SECONDS', 'private-invalid')
    assert lead_ads_cli.main(['worker', '--allow-network']) == 2
    out = capsys.readouterr().out
    assert 'operation_failed' in out and 'private-invalid' not in out
