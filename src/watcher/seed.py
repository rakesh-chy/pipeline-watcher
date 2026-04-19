"""Demo seed: pipelines + a synthetic heartbeat history that exercises each check."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from watcher.models import Heartbeat, Pipeline, RunStatus
from watcher.storage import Storage

DEMO_PIPELINES: list[Pipeline] = [
    Pipeline(
        name="orders-etl",
        description="Hourly ETL of orders into the warehouse",
        expected_interval_seconds=3600,
        owner="data-platform",
    ),
    Pipeline(
        name="user-events-stream",
        description="5-minute micro-batch of clickstream events",
        expected_interval_seconds=600,
        failure_rate_threshold=0.3,
        owner="growth",
    ),
    Pipeline(
        name="nightly-aggregations",
        description="Nightly rollup of derived tables",
        expected_interval_seconds=86400,
        owner="analytics",
    ),
    Pipeline(
        name="finance-daily-report",
        description="Daily finance roll-up",
        expected_interval_seconds=86400,
        owner="finance",
    ),
    Pipeline(
        name="status-page-mirror",
        description="Mirrors a public status JSON; freshness-checked",
        expected_interval_seconds=900,
        freshness_url="https://www.githubstatus.com/api/v2/status.json",
        owner="ops",
    ),
]


def seed_pipelines(storage: Storage) -> int:
    for p in DEMO_PIPELINES:
        storage.upsert_pipeline(p)
    return len(DEMO_PIPELINES)


def emit_demo_heartbeats(storage: Storage, *, seed: int = 7) -> int:
    # Each pipeline lands in a different state: healthy / stale / failing / quiet / freshness-only.
    rng = random.Random(seed)
    now = datetime.now(UTC)
    written = 0

    for h in range(24, 0, -1):
        ts = now - timedelta(hours=h) + timedelta(minutes=rng.randint(-2, 2))
        storage.record_heartbeat(
            Heartbeat(
                pipeline="orders-etl",
                status=RunStatus.SUCCESS,
                duration_seconds=rng.uniform(45, 180),
                ts=ts,
                message="ok",
            )
        )
        written += 1

    for m in range(30, 60 * 4, 5):
        storage.record_heartbeat(
            Heartbeat(
                pipeline="user-events-stream",
                status=RunStatus.SUCCESS,
                duration_seconds=rng.uniform(2, 8),
                ts=now - timedelta(minutes=m),
                message="ok",
            )
        )
        written += 1

    statuses = [RunStatus.SUCCESS] * 4 + [RunStatus.FAILED] * 6
    rng.shuffle(statuses)
    for i, status in enumerate(statuses):
        storage.record_heartbeat(
            Heartbeat(
                pipeline="nightly-aggregations",
                status=status,
                duration_seconds=rng.uniform(600, 1800),
                ts=now - timedelta(minutes=10 + i * 3),
                message="ok" if status is RunStatus.SUCCESS else "OOM",
            )
        )
        written += 1

    for d in range(7, 0, -1):
        ts = now - timedelta(days=d) + timedelta(minutes=rng.randint(-30, 30))
        storage.record_heartbeat(
            Heartbeat(
                pipeline="finance-daily-report",
                status=RunStatus.SUCCESS,
                duration_seconds=rng.uniform(120, 400),
                ts=ts,
                message="ok",
            )
        )
        written += 1
    storage.record_heartbeat(
        Heartbeat(
            pipeline="finance-daily-report",
            status=RunStatus.SUCCESS,
            duration_seconds=300.0,
            ts=now - timedelta(hours=4),
            message="ok",
        )
    )
    written += 1

    return written
