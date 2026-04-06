"""Pydantic models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    RUNNING = "running"


class IncidentSeverity(StrEnum):
    WARN = "warn"
    CRITICAL = "critical"


class IncidentStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class CheckKind(StrEnum):
    HEARTBEAT_MISSED = "heartbeat_missed"
    STALE_OUTPUT = "stale_output"
    FAILURE_RATE = "failure_rate"


class Pipeline(BaseModel):
    name: str
    description: str | None = None
    expected_interval_seconds: int
    freshness_url: str | None = None
    failure_rate_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    failure_rate_window_minutes: int = 60
    owner: str | None = None


class Heartbeat(BaseModel):
    pipeline: str
    status: RunStatus = RunStatus.SUCCESS
    duration_seconds: float | None = None
    message: str | None = None
    ts: datetime | None = None


class Incident(BaseModel):
    id: int | None = None
    pipeline: str
    kind: CheckKind
    severity: IncidentSeverity
    status: IncidentStatus
    opened_at: datetime
    resolved_at: datetime | None = None
    detail: str
