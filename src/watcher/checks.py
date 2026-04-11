"""SLA check evaluators. Pure functions - incident persistence lives in ``runner``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from watcher.models import CheckKind, IncidentSeverity, Pipeline
from watcher.storage import Storage


@dataclass
class CheckResult:
    pipeline: str
    kind: CheckKind
    breaching: bool
    severity: IncidentSeverity
    detail: str


def check_heartbeat(pipeline: Pipeline, storage: Storage, now: datetime | None = None) -> CheckResult:
    now = now or datetime.now(UTC)
    hb = storage.last_heartbeat(pipeline.name)
    if hb is None:
        # A never-reported pipeline isn't breaching - matches PagerDuty/Datadog.
        return CheckResult(
            pipeline=pipeline.name,
            kind=CheckKind.HEARTBEAT_MISSED,
            breaching=False,
            severity=IncidentSeverity.WARN,
            detail="no heartbeats yet",
        )
    ts = hb["ts"]
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    age = (now - ts).total_seconds()
    breaching = age > pipeline.expected_interval_seconds
    severity = (
        IncidentSeverity.CRITICAL
        if age > 2 * pipeline.expected_interval_seconds
        else IncidentSeverity.WARN
    )
    return CheckResult(
        pipeline=pipeline.name,
        kind=CheckKind.HEARTBEAT_MISSED,
        breaching=breaching,
        severity=severity,
        detail=f"last heartbeat {int(age)}s ago (expected <= {pipeline.expected_interval_seconds}s)",
    )


def check_failure_rate(pipeline: Pipeline, storage: Storage) -> CheckResult:
    rate, total = storage.failure_rate(pipeline.name, pipeline.failure_rate_window_minutes)
    if total < 3:
        # Cold-start guard: avoid alerting off 1-2 unlucky runs.
        return CheckResult(
            pipeline=pipeline.name,
            kind=CheckKind.FAILURE_RATE,
            breaching=False,
            severity=IncidentSeverity.WARN,
            detail=f"only {total} runs in window - not enough signal",
        )
    breaching = rate > pipeline.failure_rate_threshold
    severity = IncidentSeverity.CRITICAL if rate > 0.8 else IncidentSeverity.WARN
    return CheckResult(
        pipeline=pipeline.name,
        kind=CheckKind.FAILURE_RATE,
        breaching=breaching,
        severity=severity,
        detail=f"failure rate {rate:.0%} over last {pipeline.failure_rate_window_minutes}m (threshold {pipeline.failure_rate_threshold:.0%}, n={total})",
    )


def run_checks(pipeline: Pipeline, storage: Storage) -> list[CheckResult]:
    return [
        check_heartbeat(pipeline, storage),
        check_failure_rate(pipeline, storage),
    ]
