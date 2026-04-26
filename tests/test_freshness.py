"""URL freshness probe - uses httpx MockTransport, no network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx

from watcher.freshness import check_url_freshness
from watcher.models import Pipeline, RunStatus


def _pipeline(url: str = "https://example.invalid/feed", interval: int = 600) -> Pipeline:
    return Pipeline(name="mirror", expected_interval_seconds=interval, freshness_url=url)


def test_freshness_no_url_returns_none():
    p = Pipeline(name="p", expected_interval_seconds=60)
    assert check_url_freshness(p) is None


def test_freshness_fresh_resource_is_success():
    def handler(request):
        return httpx.Response(
            200,
            headers={"Last-Modified": format_datetime(datetime.now(UTC), usegmt=True)},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    hb = check_url_freshness(_pipeline(), client=client)
    assert hb is not None
    assert hb.status is RunStatus.SUCCESS


def test_freshness_stale_resource_is_failed():
    stale = datetime.now(UTC) - timedelta(hours=2)

    def handler(request):
        return httpx.Response(200, headers={"Last-Modified": format_datetime(stale, usegmt=True)})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    hb = check_url_freshness(_pipeline(interval=600), client=client)
    assert hb is not None
    assert hb.status is RunStatus.FAILED


def test_freshness_missing_header_is_failed():
    def handler(request):
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    hb = check_url_freshness(_pipeline(), client=client)
    assert hb.status is RunStatus.FAILED
    assert "missing" in hb.message.lower()


def test_freshness_http_error_is_failed():
    def handler(request):
        raise httpx.ConnectError("nope")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    hb = check_url_freshness(_pipeline(), client=client)
    assert hb.status is RunStatus.FAILED
    assert "error" in hb.message.lower()
