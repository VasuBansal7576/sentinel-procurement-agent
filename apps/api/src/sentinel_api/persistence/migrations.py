"""Small checksum-verified SQL migration runner for Sentinel-owned tables."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from psycopg import AsyncConnection

_MIGRATION_NAME: Final = re.compile(r"^(?P<version>\d{4})_[a-z0-9_]+\.sql$")
_MIGRATION_LOCK_ID: Final = 7_283_304_196_828_749_636


class MigrationError(RuntimeError):
    """Raised when applied migration history is inconsistent with source."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    name: str
    checksum: str
    sql: str


def default_migration_directory() -> Path:
    """Return the API package's SQL migration directory."""

    return Path(__file__).resolve().parents[3] / "migrations"


def discover_migrations(directory: Path | None = None) -> tuple[Migration, ...]:
    """Load ordered migrations and reject ambiguous version numbers."""

    root = directory or default_migration_directory()
    migrations: list[Migration] = []
    versions: set[str] = set()
    for path in sorted(root.glob("*.sql")):
        match = _MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"invalid migration filename: {path.name}")
        version = match.group("version")
        if version in versions:
            raise MigrationError(f"duplicate migration version: {version}")
        versions.add(version)
        sql_text = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=version,
                name=path.name,
                checksum=hashlib.sha256(sql_text.encode()).hexdigest(),
                sql=sql_text,
            )
        )
    if not migrations:
        raise MigrationError(f"no SQL migrations found in {root}")
    return tuple(migrations)


async def apply_migrations(
    connection: AsyncConnection[dict[str, object]],
    *,
    directory: Path | None = None,
) -> tuple[str, ...]:
    """Apply pending migrations under a PostgreSQL advisory transaction lock."""

    migrations = discover_migrations(directory)
    applied_now: list[str] = []
    async with connection.transaction():
        await connection.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            (_MIGRATION_LOCK_ID,),
        )
        await connection.execute("CREATE SCHEMA IF NOT EXISTS sentinel")
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sentinel.schema_migrations (
                version text PRIMARY KEY,
                name text NOT NULL UNIQUE,
                checksum text NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
            )
            """
        )
        cursor = await connection.execute(
            "SELECT version, checksum FROM sentinel.schema_migrations ORDER BY version",
        )
        rows = await cursor.fetchall()
        applied = {str(row["version"]): str(row["checksum"]) for row in rows}
        for migration in migrations:
            previous_checksum = applied.get(migration.version)
            if previous_checksum is not None:
                if previous_checksum != migration.checksum:
                    raise MigrationError(
                        f"checksum mismatch for applied migration {migration.name}"
                    )
                continue
            await connection.execute(migration.sql, prepare=False)
            await connection.execute(
                """
                INSERT INTO sentinel.schema_migrations (version, name, checksum)
                VALUES (%s, %s, %s)
                """,
                (migration.version, migration.name, migration.checksum),
            )
            applied_now.append(migration.version)
    return tuple(applied_now)
