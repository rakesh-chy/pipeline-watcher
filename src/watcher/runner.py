"""Evaluator loop: probe freshness, run checks, open/resolve incidents, fire alerts."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from watcher.alerter import Alerter
from watcher.checks import CheckResult, run_checks
from watcher.freshness import check_url_freshness
from watcher.storage import Storage

logger = logging.getLogger(__name__)


@dataclass
class RunSummary:
    pipelines_checked: int
    checks_run: int
    incidents_opened: int
    incidents_resolved: int
    results: list[CheckResult]


def evaluate_once(storage: Storage, alerter: Alerter | None = None) -> RunSummary:
    alerter = alerter or Alerter(settings=storage.settings)
    opened = 0
    resolved = 0
    all_results: list[CheckResult] = []

    pipelines = storage.list_pipelines()
    for p in pipelines:
        if p.freshness_url:
            hb = check_url_freshness(p)
            if hb is not None:
                storage.record_heartbeat(hb)

        results = run_checks(p, storage)
        all_results.extend(results)

        for r in results:
            if r.breaching:
                new_id = storage.open_incident(r.pipeline, r.kind, r.severity, r.detail)
                if new_id is not None:
                    opened += 1
                    alerter.fire_opened(r)
                    logger.info("opened incident #%s for %s/%s", new_id, r.pipeline, r.kind.value)
            else:
                n = storage.resolve_incidents(r.pipeline, r.kind)
                if n:
                    resolved += n
                    alerter.fire_resolved(r.pipeline, r.kind.value)
                    logger.info("resolved %d incident(s) for %s/%s", n, r.pipeline, r.kind.value)

    return RunSummary(
        pipelines_checked=len(pipelines),
        checks_run=len(all_results),
        incidents_opened=opened,
        incidents_resolved=resolved,
        results=all_results,
    )
