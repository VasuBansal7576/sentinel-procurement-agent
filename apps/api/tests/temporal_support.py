"""Shared gate for Temporal test-server suites.

Ephemeral Temporal test servers download a platform binary. That path is
reliable locally but often flaky or unavailable on bare CI runners. Mirror the
Postgres pattern: opt-in with SENTINEL_RUN_TEMPORAL_TESTS=1.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from temporalio.testing import WorkflowEnvironment

_TEMPORAL_DOWNLOAD_DIR = Path(
    os.environ.get(
        "SENTINEL_TEMPORAL_TEST_SERVER_DIR",
        "/tmp/sentinel-temporal-test-server",
    )
)


def require_temporal_test_server() -> None:
    if os.environ.get("SENTINEL_RUN_TEMPORAL_TESTS") != "1":
        pytest.skip("set SENTINEL_RUN_TEMPORAL_TESTS=1 to run Temporal test-server suites")


@asynccontextmanager
async def temporal_time_skipping_env() -> AsyncIterator[WorkflowEnvironment]:
    """Start a time-skipping Temporal test environment or skip when unavailable."""

    require_temporal_test_server()
    _TEMPORAL_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        async with await WorkflowEnvironment.start_time_skipping(
            download_dest_dir=str(_TEMPORAL_DOWNLOAD_DIR)
        ) as environment:
            yield environment
    except RuntimeError as error:
        message = str(error)
        if "Failed starting test server" in message or "No such file" in message:
            pytest.skip(f"Temporal test server unavailable: {error}")
        raise
