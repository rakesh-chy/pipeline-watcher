"""Postgres storage layer.

Thin wrapper around psycopg with a connection pool. No ORM - schema lives in
``init_schema`` and queries are written by hand to keep them inspectable.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from watcher.config import Settings, get_settings
from watcher.models import (
    CheckKind,
    Heartbeat,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    Pipeline,
    RunStatus,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pipelines (
    name                         TEXT PRIMARY KEY,
    description                  TEXT,
    expected_interval_seconds    INTEGER NOT NULL,
    freshness_url                TEXT,
    failure_rate_threshold       DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    failure_rate_window_minutes  INTEGER NOT NULL DEFAULT 60,
    owner                        TEXT,
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS heartbeats (
    id                BIGSERIAL PRIMARY KEY,
    pipeline          TEXT NOT NULL REFERENCES pipelines(name) ON DELETE CASCADE,
    status            TEXT NOT NULL,
    duration_seconds  DOUBLE PRECISION,
    message           TEXT,
    ts                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS heartbeats_pipeline_ts_idx
    ON heartbeats (pipeline, ts DESC);

CREATE TABLE IF NOT EXISTS incidents (
    id           BIGSERIAL PRIMARY KEY,
    pipeline     TEXT NOT NULL REFERENCES pipelines(name) ON DELETE CASCADE,
    kind         TEXT NOT NULL,
    severity     TEXT NOT NULL,
    status       TEXT NOT NULL,
    opened_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at  TIMESTAMPTZ,
    detail       TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS incidents_open_unique_idx
    ON incidents (pipeline, kind) WHERE status = 'open';

CREATE INDEX IF NOT EXISTS incidents_status_idx
    ON incidents (status, opened_at DESC);
"""


class Storage:
    def __init__(self, settings: Settings | None = None, pool: ConnectionPool | None = None):
        self.settings = settings or get_settings()
        self.pool = pool or ConnectionPool(
            conninfo=self.settings.database_url,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
            open=True,
        )

    def close(self) -> None:
        self.pool.close()

    @contextmanager
    def conn(self) -> Iterator[psycopg.Connection]:
        with self.pool.connection() as c:
            yield c

    def init_schema(self) -> None:
        with self.conn() as c, c.cursor() as cur:
            cur.execute(SCHEMA_SQL)
            c.commit()

    def drop_schema(self) -> None:
        with self.conn() as c, c.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS incidents, heartbeats, pipelines CASCADE;")
            c.commit()

    def upsert_pipeline(self, p: Pipeline) -> None:
        with self.conn() as c, c.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pipelines
                    (name, description, expected_interval_seconds, freshness_url,
                     failure_rate_threshold, failure_rate_window_minutes, owner)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    expected_interval_seconds = EXCLUDED.expected_interval_seconds,
                    freshness_url = EXCLUDED.freshness_url,
                    failure_rate_threshold = EXCLUDED.failure_rate_threshold,
                    failure_rate_window_minutes = EXCLUDED.failure_rate_window_minutes,
                    owner = EXCLUDED.owner
                """,
                (
                    p.name,
                    p.description,
                    p.expected_interval_seconds,
                    p.freshness_url,
                    p.failure_rate_threshold,
                    p.failure_rate_window_minutes,
                    p.owner,
                ),
            )
            c.commit()

    def list_pipelines(self) -> list[Pipeline]:
        with self.conn() as c, c.cursor() as cur:
            cur.execute("SELECT * FROM pipelines ORDER BY name")
            return [Pipeline(**row) for row in cur.fetchall()]

    def get_pipeline(self, name: str) -> Pipeline | None:
        with self.conn() as c, c.cursor() as cur:
            cur.execute("SELECT * FROM pipelines WHERE name = %s", (name,))
            row = cur.fetchone()
            return Pipeline(**row) if row else None

    def delete_pipeline(self, name: str) -> None:
        with self.conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM pipelines WHERE name = %s", (name,))
            c.commit()

    def record_heartbeat(self, hb: Heartbeat) -> int:
        with self.conn() as c, c.cursor() as cur:
            cur.execute(
                """
                INSERT INTO heartbeats (pipeline, status, duration_seconds, message, ts)
                VALUES (%s, %s, %s, %s, COALESCE(%s, NOW()))
                RETURNING id
                """,
                (hb.pipeline, hb.status.value, hb.duration_seconds, hb.message, hb.ts),
            )
            row = cur.fetchone()
            c.commit()
            return row["id"]

    def last_heartbeat(self, pipeline: str) -> dict | None:
        with self.conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT * FROM heartbeats WHERE pipeline = %s ORDER BY ts DESC LIMIT 1",
                (pipeline,),
            )
            return cur.fetchone()

    def recent_heartbeats(self, pipeline: str, window_minutes: int) -> list[dict]:
        cutoff = datetime.now(UTC) - timedelta(minutes=window_minutes)
        with self.conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT * FROM heartbeats WHERE pipeline = %s AND ts >= %s ORDER BY ts DESC",
                (pipeline, cutoff),
            )
            return cur.fetchall()

    def failure_rate(self, pipeline: str, window_minutes: int) -> tuple[float, int]:
        with self.conn() as c, c.cursor() as cur:
            cutoff = datetime.now(UTC) - timedelta(minutes=window_minutes)
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = %s)::float / NULLIF(COUNT(*), 0) AS rate,
                    COUNT(*)::int AS total
                FROM heartbeats
                WHERE pipeline = %s AND ts >= %s
                """,
                (RunStatus.FAILED.value, pipeline, cutoff),
            )
            row = cur.fetchone()
            rate = row["rate"] or 0.0
            return float(rate), int(row["total"])

    def open_incident(
        self, pipeline: str, kind: CheckKind, severity: IncidentSeverity, detail: str
    ) -> int | None:
        """Returns the new incident id, or ``None`` if one is already open."""
        with self.conn() as c, c.cursor() as cur:
            cur.execute(
                """
                INSERT INTO incidents (pipeline, kind, severity, status, detail)
                VALUES (%s, %s, %s, 'open', %s)
                ON CONFLICT (pipeline, kind) WHERE status = 'open' DO NOTHING
                RETURNING id
                """,
                (pipeline, kind.value, severity.value, detail),
            )
            row = cur.fetchone()
            c.commit()
            return row["id"] if row else None

    def resolve_incidents(self, pipeline: str, kind: CheckKind) -> int:
        with self.conn() as c, c.cursor() as cur:
            cur.execute(
                """
                UPDATE incidents
                SET status = 'resolved', resolved_at = NOW()
                WHERE pipeline = %s AND kind = %s AND status = 'open'
                """,
                (pipeline, kind.value),
            )
            n = cur.rowcount
            c.commit()
            return n

    def list_incidents(self, status: IncidentStatus | None = None) -> list[Incident]:
        sql = "SELECT * FROM incidents"
        params: tuple = ()
        if status is not None:
            sql += " WHERE status = %s"
            params = (status.value,)
        sql += " ORDER BY opened_at DESC LIMIT 200"
        with self.conn() as c, c.cursor() as cur:
            cur.execute(sql, params)
            return [Incident(**row) for row in cur.fetchall()]
