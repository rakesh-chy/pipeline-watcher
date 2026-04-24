"""SLA check evaluators."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from watcher.checks import check_failure_rate, check_heartbeat
from watcher.models import CheckKind, Heartbeat, IncidentSeverity, Pipeline, RunStatus


def _pipeline(**overrides) -> Pipeline:
    base = dict(
        name="p1",
        expected_interval_seconds=600,
        failure_rate_threshold=0.5,
        failure_rate_window_minutes=60,
    )
    base.update(overrides)
    return Pipeline(**base)


def test_heartbeat_check_no_history_is_not_breaching(storage):
    p = _pipeline()
    storage.upsert_pipeline(p)
    r = check_heartbeat(p, storage)
    assert r.kind is CheckKind.HEARTBEAT_MISSED
    assert r.breaching is False


def test_heartbeat_check_fresh_is_ok(storage):
    p = _pipeline()
    storage.upsert_pipeline(p)
    storage.record_heartbeat(Heartbeat(pipeline=p.name, status=RunStatus.SUCCESS))
    r = check_heartbeat(p, storage)
    assert r.breaching is False


def test_heartbeat_check_stale_breaches_warn(storage):
    p = _pipeline(expected_interval_seconds=60)
    storage.upsert_pipeline(p)
    storage.record_heartbeat(
        Heartbeat(
            pipeline=p.name,
            status=RunStatus.SUCCESS,
            ts=datetime.now(UTC) - timedelta(seconds=90),
        )
    )
    r = check_heartbeat(p, storage)
    assert r.breaching is True
    assert r.severity is IncidentSeverity.WARN


def test_heartbeat_check_very_stale_breaches_critical(storage):
    p = _pipeline(expected_interval_seconds=60)
    storage.upsert_pipeline(p)
    storage.record_heartbeat(
        Heartbeat(
            pipeline=p.name,
            status=RunStatus.SUCCESS,
            ts=datetime.now(UTC) - timedelta(seconds=300),
        )
    )
    r = check_heartbeat(p, storage)
    assert r.breaching is True
    assert r.severity is IncidentSeverity.CRITICAL


def test_failure_rate_insufficient_signal(storage):
    p = _pipeline()
    storage.upsert_pipeline(p)
    storage.record_heartbeat(Heartbeat(pipeline=p.name, status=RunStatus.FAILED))
    r = check_failure_rate(p, storage)
    assert r.breaching is False
    assert "not enough signal" in r.detail


def test_failure_rate_breaches_when_above_threshold(storage):
    p = _pipeline(failure_rate_threshold=0.5)
    storage.upsert_pipeline(p)
    now = datetime.now(UTC)
    for s in [RunStatus.FAILED] * 4 + [RunStatus.SUCCESS] * 1:
        storage.record_heartbeat(Heartbeat(pipeline=p.name, status=s, ts=now))
    r = check_failure_rate(p, storage)
    assert r.breaching is True


def test_failure_rate_under_threshold_is_ok(storage):
    p = _pipeline(failure_rate_threshold=0.5)
    storage.upsert_pipeline(p)
    now = datetime.now(UTC)
    for s in [RunStatus.SUCCESS] * 4 + [RunStatus.FAILED] * 1:
        storage.record_heartbeat(Heartbeat(pipeline=p.name, status=s, ts=now))
    r = check_failure_rate(p, storage)
    assert r.breaching is False
