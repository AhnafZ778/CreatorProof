"""Explicitly opt-in PostgreSQL integration test using disposable Docker only."""

import os

import pytest

from scripts.phase1_postgres_verify import verify_postgres


@pytest.mark.skipif(
    os.environ.get("CREATORPROOF_RUN_DISPOSABLE_POSTGRES") != "1",
    reason="Set CREATORPROOF_RUN_DISPOSABLE_POSTGRES=1 to run disposable Docker integration",
)
def test_disposable_postgresql_migrations_rls_and_immutable_guards():
    report = verify_postgres()
    assert report["passed"] is True
    assert report["container_removed"] is True
    assert report["server_version"].startswith("17.")
    assert "APPLICATION_STARTUP_AND_AUTHENTICATED_ROUTE_WITH_RUNTIME_ROLE" in report["checks"]
    assert "ONE_ATTRIBUTABLE_HUMAN_DISPOSITION_WITH_IMMUTABLE_PROVIDER_CONTENT" in report["checks"]
