"""Storage layer round-trips."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from watcher.models import (
    CheckKind,
    Heartbeat,
    IncidentSeverity,
    IncidentStatus,
    Pipeline,
    RunStatus,
)


def _pipeline(name: str = "p1", interval: int = 600) -> Pipeline:
    return Pipeline(name=name, expected_interval_seconds=interval, owner="qa")


def test_upsert_and_get_pipeline(storage):
    storage.upsert_pipeline(_pipeline("orders"))
    got = storage.get_pipeline("orders")
    assert got is not None
    assert got.name == "orders"
    assert got.expected_interval_seconds == 600


def test_upsert_is_idempotent(storage):
    storage.upsert_pipeline(_pipeline("orders", 600))
    storage.upsert_pipeline(_pipeline("orders", 900))
    got = storage.get_pipeline("orders")
    assert got.expected_interval_seconds == 900
    assert len(storage.list_pipelines()) == 1


def test_record_and_fetch_heartbeat(storage):
    storage.upsert_pipeline(_pipeline("p"))
    hb_id = storage.record_heartbeat(Heartbeat(pipeline="p", status=RunStatus.SUCCESS, message="ok"))
    assert hb_id > 0
    last = storage.last_heartbeat("p")
    assert last is not None
    assert last["status"] == "success"


def test_failure_rate(storage):
    storage.upsert_pipeline(_pipeline("p", 600))
    now = datetime.now(UTC)
    for status in [RunStatus.SUCCESS, RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.FAILED, RunStatus.FAILED]:
        storage.record_heartbeat(
            Heartbeat(pipeline="p", status=status, ts=now - timedelta(minutes=5))
        )
    rate, total = storage.failure_rate("p", window_minutes=60)
    assert total == 5
    assert rate == 0.6


def test_open_incident_is_deduped(storage):
    storage.upsert_pipeline(_pipeline("p"))
    first = storage.open_incident("p", CheckKind.HEARTBEAT_MISSED, IncidentSeverity.WARN, "stale")
    second = storage.open_incident("p", CheckKind.HEARTBEAT_MISSED, IncidentSeverity.WARN, "stale again")
    assert first is not None
    assert second is None
    assert len(storage.list_incidents(IncidentStatus.OPEN)) == 1


def test_resolve_incident_flips_status(storage):
    storage.upsert_pipeline(_pipeline("p"))
    storage.open_incident("p", CheckKind.HEARTBEAT_MISSED, IncidentSeverity.WARN, "stale")
    n = storage.resolve_incidents("p", CheckKind.HEARTBEAT_MISSED)
    assert n == 1
    assert len(storage.list_incidents(IncidentStatus.OPEN)) == 0
    assert len(storage.list_incidents(IncidentStatus.RESOLVED)) == 1


def test_resolve_then_reopen_is_allowed(storage):
    """After resolving, a new incident for the same (pipeline, kind) can be opened."""
    storage.upsert_pipeline(_pipeline("p"))
    storage.open_incident("p", CheckKind.HEARTBEAT_MISSED, IncidentSeverity.WARN, "round 1")
    storage.resolve_incidents("p", CheckKind.HEARTBEAT_MISSED)
    new_id = storage.open_incident("p", CheckKind.HEARTBEAT_MISSED, IncidentSeverity.CRITICAL, "round 2")
    assert new_id is not None
