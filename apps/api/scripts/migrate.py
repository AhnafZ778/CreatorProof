"""Migration helper with backup and rollback evidence.

A destructive migration must be preceded by a restorable backup. For SQLite the
backup is a file copy; for PostgreSQL the command prints the exact ``pg_dump``
invocation to run, because the tool refuses to pretend it made a backup it did
not make.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config

from app.core.config import Settings

API_ROOT = Path(__file__).resolve().parent.parent


def _config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _backup(database_url: str, backup_dir: Path) -> dict:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir.mkdir(parents=True, exist_ok=True)
    if database_url.startswith("sqlite"):
        source = Path(urlparse(database_url).path or database_url.split("///")[-1])
        if not source.exists():
            return {"performed": False, "reason": "SQLITE_FILE_DOES_NOT_EXIST_YET"}
        target = backup_dir / f"creatorproof-{stamp}.db"
        shutil.copy2(source, target)
        return {"performed": True, "kind": "sqlite-file-copy", "path": str(target)}
    target = backup_dir / f"creatorproof-{stamp}.dump"
    return {
        "performed": False,
        "kind": "postgresql",
        "required_command": f"pg_dump --format=custom --file={target} '{database_url}'",
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
