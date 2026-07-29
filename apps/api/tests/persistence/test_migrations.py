"""Static guarantees for the migration chain that do not require PostgreSQL."""

from pathlib import Path

import pytest

from sentinel_api.persistence.migrations import MigrationError, discover_migrations


def test_migrations_are_ordered_and_cover_required_storage() -> None:
    migrations = discover_migrations()

    assert [migration.version for migration in migrations] == [
        "0001",
        "0002",
        "0003",
        "0004",
    ]
    combined = "\n".join(migration.sql for migration in migrations)
    for table in (
        "sentinel.runs",
        "sentinel.run_events",
        "sentinel.event_outbox",
        "sentinel.run_projection",
        "sentinel.work_item_projection",
        "sentinel.subagent_projection",
        "sentinel.proposals",
        "sentinel.proposal_versions",
        "sentinel.approval_permits",
        "sentinel.action_intents",
        "sentinel.action_outcomes",
    ):
        assert f"CREATE TABLE {table}" in combined
    assert "event_outbox_pending_idx" in combined
    assert "reject_journal_mutation" in combined
    assert "UNIQUE (run_id, per_run_sequence)" in combined
    assert "provider_request_fingerprint" in combined


def test_migration_discovery_rejects_duplicate_versions(tmp_path: Path) -> None:
    (tmp_path / "0001_first.sql").write_text("SELECT 1", encoding="utf-8")
    (tmp_path / "0001_second.sql").write_text("SELECT 2", encoding="utf-8")

    with pytest.raises(MigrationError, match="duplicate migration version"):
        discover_migrations(tmp_path)


def test_migration_discovery_rejects_unversioned_sql(tmp_path: Path) -> None:
    (tmp_path / "latest.sql").write_text("SELECT 1", encoding="utf-8")

    with pytest.raises(MigrationError, match="invalid migration filename"):
        discover_migrations(tmp_path)
