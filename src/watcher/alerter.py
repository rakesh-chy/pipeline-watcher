"""Slack alerter. Falls back to logging when no webhook is configured."""

from __future__ import annotations

import logging

import httpx

from watcher.checks import CheckResult
from watcher.config import Settings, get_settings
from watcher.models import IncidentSeverity

logger = logging.getLogger(__name__)


class Alerter:
    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None):
        self.settings = settings or get_settings()
        self.client = client or httpx.Client(timeout=10.0)

    def close(self) -> None:
        self.client.close()

    def _enabled(self) -> bool:
        return bool(self.settings.alerts_enabled and self.settings.slack_webhook_url)

    def fire_opened(self, result: CheckResult) -> bool:
        text = self._format_opened(result)
        return self._send(text, result.severity)

    def fire_resolved(self, pipeline: str, kind: str) -> bool:
        text = f"[RESOLVED] `{pipeline}` / `{kind}`"
        return self._send(text, IncidentSeverity.WARN)

    def _format_opened(self, r: CheckResult) -> str:
        return (
            f"[{r.severity.value.upper()}] `{r.pipeline}` / `{r.kind.value}`\n"
            f"> {r.detail}"
        )

    def _send(self, text: str, severity: IncidentSeverity) -> bool:
        if not self._enabled():
            logger.info("[alert/%s] %s", severity.value, text)
            return False
        resp = self.client.post(
            self.settings.slack_webhook_url,  # type: ignore[arg-type]
            json={"text": text},
        )
        if resp.status_code >= 400:
            logger.warning("Slack webhook returned %s: %s", resp.status_code, resp.text)
            return False
        return True
