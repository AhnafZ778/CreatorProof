"""Migration helper with backup and rollback evidence.

A destructive migration must be preceded by a restorable backup. For SQLite the
online backup includes committed WAL data. For PostgreSQL the helper prints a
credential-free ``pg_dump`` template, because deployment logs must never contain
a connection URL and the tool refuses to pretend it made a backup it did not make.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.core.config import Settings

API_ROOT = Path(__file__).resolve().parent.parent


def _config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _backup(database_url: str, backup_dir: Path) -> dict:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() == "sqlite":
        database = parsed_url.database
        if not database or database == ":memory:":
            return {"performed": False, "reason": "SQLITE_DATABASE_IS_IN_MEMORY"}
        if str(parsed_url.query.get("uri", "false")).lower() == "true":
            return {"performed": False, "reason": "SQLITE_URI_BACKUP_REQUIRES_EXPLICIT_FILE_PATH"}
        source = Path(database).resolve()
        if not source.is_file():
            return {"performed": False, "reason": "SQLITE_FILE_DOES_NOT_EXIST_YET"}
        # mode=ro also prevents a missing source from being created between the
        # filesystem check and opening it. as_uri safely quotes spaces/#/? etc.
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
            backup_dir.mkdir(parents=True, exist_ok=True)
            descriptor, filename = tempfile.mkstemp(
                prefix=f"creatorproof-{stamp}-", suffix=".db", dir=backup_dir
            )
            os.close(descriptor)
            target = Path(filename)
            try:
                with closing(sqlite3.connect(target)) as destination:
                    original.backup(destination)
                    if destination.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                        raise sqlite3.DatabaseError("SQLite backup integrity check failed")
            except BaseException:
                target.unlink(missing_ok=True)
                raise
        return {
            "performed": True,
            "kind": "sqlite-online-backup",
            "path": str(target),
            "verified_by": "PRAGMA quick_check",
        }
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"creatorproof-{stamp}.dump"
    return {
        "performed": False,
        "kind": "postgresql",
        "required_command": (
            f'pg_dump --format=custom --file={target} --dbname="$CREATORPROOF_DATABASE_URL"'
        ),
        "reason": "RUN_PG_DUMP_AND_VERIFY_RESTORE_BEFORE_A_DESTRUCTIVE_MIGRATION",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CreatorProof database migrations.")
    parser.add_argument(
        "action", choices=["upgrade", "downgrade", "current", "history", "stamp", "backup"]
    )
    parser.add_argument("--revision", default="head")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--backup-dir", default=str(API_ROOT / "data" / "backups"))
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Skip the pre-migration backup. Not permitted for downgrade.",
    )
    args = parser.parse_args()
    if args.action == "downgrade" and args.skip_backup:
        parser.error("--skip-backup is not permitted for downgrade")

    database_url = args.database_url or Settings().database_url
    config = _config(database_url)

    if args.action in {"upgrade", "downgrade", "backup"} and not args.skip_backup:
        evidence = _backup(database_url, Path(args.backup_dir))
        print(json.dumps({"backup": evidence}, indent=2))
        if args.action == "downgrade" and not evidence.get("performed"):
            print(
                "Refusing to downgrade without a verified backup. "
                "Take the backup above, verify a restore, then re-run.",
                file=sys.stderr,
            )
            return 2
        if args.action == "backup":
            return 0

    if args.action == "upgrade":
        command.upgrade(config, args.revision)
    elif args.action == "downgrade":
        command.downgrade(config, args.revision)
    elif args.action == "current":
        command.current(config, verbose=True)
    elif args.action == "history":
        command.history(config, verbose=True)
    elif args.action == "stamp":
        command.stamp(config, args.revision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
