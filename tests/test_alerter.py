"""Slack alerter - uses httpx MockTransport, no network."""

from __future__ import annotations

import httpx

from watcher.alerter import Alerter
from watcher.checks import CheckResult
from watcher.config import Settings
from watcher.models import CheckKind, IncidentSeverity


def _result(severity=IncidentSeverity.WARN) -> CheckResult:
    return CheckResult(
        pipeline="orders",
        kind=CheckKind.HEARTBEAT_MISSED,
        breaching=True,
        severity=severity,
        detail="stale 5m",
    )


def test_alerter_disabled_does_not_post():
    posted = []

    def handler(request):
        posted.append(request)
        return httpx.Response(200)

    settings = Settings(alerts_enabled=False, slack_webhook_url="https://hooks.invalid/x")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    alerter = Alerter(settings=settings, client=client)

    sent = alerter.fire_opened(_result())
    assert sent is False
    assert posted == []


def test_alerter_enabled_posts_to_webhook():
    posted = []

    def handler(request):
        posted.append(request)
        return httpx.Response(200)

    settings = Settings(alerts_enabled=True, slack_webhook_url="https://hooks.invalid/x")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    alerter = Alerter(settings=settings, client=client)

    sent = alerter.fire_opened(_result(IncidentSeverity.CRITICAL))
    assert sent is True
    assert len(posted) == 1
    body = posted[0].read().decode()
    assert "orders" in body
    assert "CRITICAL" in body


def test_alerter_post_4xx_returns_false():
    def handler(request):
        return httpx.Response(500, text="boom")

    settings = Settings(alerts_enabled=True, slack_webhook_url="https://hooks.invalid/x")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    alerter = Alerter(settings=settings, client=client)
    assert alerter.fire_opened(_result()) is False


def test_alerter_resolved_message():
    posted = []

    def handler(request):
        posted.append(request)
        return httpx.Response(200)

    settings = Settings(alerts_enabled=True, slack_webhook_url="https://hooks.invalid/x")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    alerter = Alerter(settings=settings, client=client)
    alerter.fire_resolved("orders", "heartbeat_missed")
    body = posted[0].read().decode()
    assert "RESOLVED" in body
    assert "orders" in body
