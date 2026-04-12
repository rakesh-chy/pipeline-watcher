"""Last-Modified freshness probe for pipelines that produce a URL-addressable output."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from watcher.models import Heartbeat, Pipeline, RunStatus


def check_url_freshness(pipeline: Pipeline, *, client: httpx.Client | None = None) -> Heartbeat | None:
    if not pipeline.freshness_url:
        return None

    own_client = client is None
    client = client or httpx.Client(timeout=10.0, follow_redirects=True)
    try:
        try:
            resp = client.head(pipeline.freshness_url)
            # Some origins don't set Last-Modified on HEAD - retry with GET.
            if resp.status_code >= 400 or "last-modified" not in (k.lower() for k in resp.headers):
                resp = client.get(pipeline.freshness_url)
        except httpx.HTTPError as exc:
            return Heartbeat(
                pipeline=pipeline.name,
                status=RunStatus.FAILED,
                message=f"freshness probe error: {exc}",
            )

        last_modified = resp.headers.get("last-modified")
        if not last_modified:
            return Heartbeat(
                pipeline=pipeline.name,
                status=RunStatus.FAILED,
                message=f"freshness probe missing Last-Modified ({resp.status_code})",
            )

        try:
            lm_dt = parsedate_to_datetime(last_modified)
        except (TypeError, ValueError):
            return Heartbeat(
                pipeline=pipeline.name,
                status=RunStatus.FAILED,
                message=f"unparseable Last-Modified: {last_modified!r}",
            )

        age = (datetime.now(UTC) - lm_dt).total_seconds()
        status = (
            RunStatus.SUCCESS if age <= pipeline.expected_interval_seconds else RunStatus.FAILED
        )
        try:
            elapsed = resp.elapsed.total_seconds()
        except RuntimeError:
            elapsed = None  # httpx MockTransport doesn't populate this.
        return Heartbeat(
            pipeline=pipeline.name,
            status=status,
            duration_seconds=elapsed,
            message=f"resource age {int(age)}s",
        )
    finally:
        if own_client:
            client.close()
