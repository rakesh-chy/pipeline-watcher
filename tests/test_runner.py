"""End-to-end runner: open/resolve incident cycle, alerter wiring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from watcher.alerter import Alerter
from watcher.checks import CheckResult
from watcher.config import Settings
from watcher.models import (
    CheckKind,
    Heartbeat,
    IncidentSeverity,
    IncidentStatus,
    Pipeline,
    RunStatus,
)
from watcher.runner import evaluate_once


class RecordingAlerter(Alerter):
    def __init__(self):
        super().__init__(settings=Settings(alerts_enabled=False))
        self.opened: list[CheckResult] = []
        self.resolved: list[tuple[str, str]] = []

    def fire_opened(self, result):
        self.opened.append(result)
        return True

    def fire_resolved(self, pipeline, kind):
        self.resolved.append((pipeline, kind))
        return True


def _stale_pipeline(name="orders") -> Pipeline:
    return Pipeline(name=name, expected_interval_seconds=60, owner="qa")


def test_runner_opens_incident_for_stale_pipeline(storage):
    p = _stale_pipeline()
    storage.upsert_pipeline(p)
    storage.record_heartbeat(
        Heartbeat(
            pipeline=p.name,
            status=RunStatus.SUCCESS,
            ts=datetime.now(UTC) - timedelta(seconds=300),
        )
    )
    alerter = RecordingAlerter()
    summary = evaluate_once(storage, alerter=alerter)
    assert summary.incidents_opened == 1
    assert len(alerter.opened) == 1
    assert alerter.opened[0].kind is CheckKind.HEARTBEAT_MISSED
    assert alerter.opened[0].severity is IncidentSeverity.CRITICAL


def test_runner_resolves_incident_when_heartbeat_returns(storage):
    p = _stale_pipeline()
    storage.upsert_pipeline(p)
    storage.record_heartbeat(
        Heartbeat(
            pipeline=p.name,
            status=RunStatus.SUCCESS,
            ts=datetime.now(UTC) - timedelta(seconds=300),
        )
    )
    evaluate_once(storage, alerter=RecordingAlerter())
    assert len(storage.list_incidents(IncidentStatus.OPEN)) == 1

    storage.record_heartbeat(Heartbeat(pipeline=p.name, status=RunStatus.SUCCESS))
    alerter = RecordingAlerter()
    summary = evaluate_once(storage, alerter=alerter)
    assert summary.incidents_resolved == 1
    assert len(storage.list_incidents(IncidentStatus.OPEN)) == 0
    assert alerter.resolved == [(p.name, CheckKind.HEARTBEAT_MISSED.value)]


def test_runner_does_not_double_alert(storage):
    p = _stale_pipeline()
    storage.upsert_pipeline(p)
    storage.record_heartbeat(
        Heartbeat(
            pipeline=p.name,
            status=RunStatus.SUCCESS,
            ts=datetime.now(UTC) - timedelta(seconds=300),
        )
    )
    alerter = RecordingAlerter()
    evaluate_once(storage, alerter=alerter)
    evaluate_once(storage, alerter=alerter)
    assert len(alerter.opened) == 1
