"""Test fixtures. Requires Postgres at ``WATCHER_TEST_DATABASE_URL``; skips cleanly otherwise."""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from watcher.config import Settings
from watcher.storage import Storage


def _test_db_url() -> str:
    return os.environ.get(
        "WATCHER_TEST_DATABASE_URL",
        "postgresql://watcher:watcher@localhost:5432/watcher_test",
    )


def _postgres_available(url: str) -> bool:
    try:
        with psycopg.connect(url, connect_timeout=2):
            return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _test_db_url()
    if not _postgres_available(url):
        pytest.skip(f"Postgres not reachable at {url} - run `docker compose up -d postgres`")
    return url


@pytest.fixture
def storage(database_url: str) -> Storage:
    """Fresh schema per test, dropped on teardown."""
    schema = f"test_{uuid.uuid4().hex[:8]}"
    base = psycopg.connect(database_url, autocommit=True)
    with base.cursor() as cur:
        cur.execute(f'CREATE SCHEMA "{schema}"')
    base.close()

    settings = Settings(
        database_url=f"{database_url}?options=-csearch_path%3D{schema}",
    )
    st = Storage(settings=settings)
    st.init_schema()
    yield st
    st.close()

    base = psycopg.connect(database_url, autocommit=True)
    with base.cursor() as cur:
        cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
    base.close()
