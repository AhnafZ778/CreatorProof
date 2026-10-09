import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy.engine import URL

from scripts.migrate import _backup, main


def test_postgres_backup_instruction_never_contains_credentials(tmp_path):
    database_url = "postgresql+psycopg://owner:top-secret@db.internal/creatorproof"
    evidence = _backup(database_url, tmp_path)

    assert evidence["performed"] is False
    assert "$CREATORPROOF_DATABASE_URL" in evidence["required_command"]
    assert database_url not in str(evidence)
    assert "top-secret" not in str(evidence)


@pytest.mark.parametrize("absolute", [False, True])
def test_sqlite_backup_resolves_relative_and_absolute_database_paths(
    tmp_path, monkeypatch, absolute
):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "nested directory" / "creator proof#.db"
    source.parent.mkdir()
    with closing(sqlite3.connect(source)) as database:
        database.execute("CREATE TABLE evidence (value TEXT NOT NULL)")
        database.execute("INSERT INTO evidence VALUES ('committed evidence')")
        database.commit()
    location = source if absolute else source.relative_to(tmp_path)
    database_url = URL.create("sqlite+pysqlite", database=str(location)).render_as_string()

    evidence = _backup(database_url, tmp_path / "backups")

    assert evidence["performed"] is True
    assert evidence["kind"] == "sqlite-online-backup"
    assert evidence["verified_by"] == "PRAGMA quick_check"
    with closing(sqlite3.connect(evidence["path"])) as restored:
        assert restored.execute("SELECT value FROM evidence").fetchall() == [
            ("committed evidence",)
        ]
    assert source.exists()


def test_sqlite_backup_restores_committed_wal_rows_without_sidecar_files(tmp_path):
    source = tmp_path / "wal-source.db"
    with closing(sqlite3.connect(source)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE evidence (value TEXT NOT NULL)")
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute("INSERT INTO evidence VALUES ('committed only in WAL')")
        writer.commit()
        assert Path(str(source) + "-wal").stat().st_size > 0
        # Keep the writer open so its close cannot checkpoint committed rows
        # into the main file before the backup path is exercised.
        evidence = _backup(f"sqlite:///{source}", tmp_path / "backups")
        assert evidence["performed"] is True
        backup = Path(evidence["path"])
        assert not Path(str(backup) + "-wal").exists()
        assert not Path(str(backup) + "-shm").exists()
        # Restore from the one backup file, with neither original sidecar.
        restored_path = tmp_path / "restored.db"
        restored_path.write_bytes(backup.read_bytes())
        with closing(sqlite3.connect(restored_path)) as restored:
            assert restored.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert restored.execute("SELECT value FROM evidence").fetchall() == [
                ("committed only in WAL",)
            ]


def test_sqlite_backup_never_creates_a_missing_database(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "missing.db"
    evidence = _backup("sqlite:///./missing.db", tmp_path / "backups")
    assert evidence == {"performed": False, "reason": "SQLITE_FILE_DOES_NOT_EXIST_YET"}
    assert not source.exists()
    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize("database_url", ["sqlite://", "sqlite:///:memory:"])
def test_sqlite_in_memory_database_has_no_file_backup(tmp_path, database_url):
    evidence = _backup(database_url, tmp_path / "backups")
    assert evidence["performed"] is False
    assert evidence["reason"] == "SQLITE_DATABASE_IS_IN_MEMORY"


def test_sqlite_uri_database_is_refused_without_creating_a_literal_uri_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    evidence = _backup("sqlite:///file:missing.db?uri=true", tmp_path / "backups")
    assert evidence["performed"] is False
    assert evidence["reason"] == "SQLITE_URI_BACKUP_REQUIRES_EXPLICIT_FILE_PATH"
    assert not (tmp_path / "file:missing.db").exists()
    assert not (tmp_path / "missing.db").exists()


def test_sqlite_backup_does_not_overwrite_an_existing_backup(tmp_path):
    source = tmp_path / "source.db"
    with closing(sqlite3.connect(source)) as database:
        database.execute("CREATE TABLE evidence (value TEXT NOT NULL)")
        database.commit()
    first = _backup(f"sqlite:///{source}", tmp_path / "backups")
    second = _backup(f"sqlite:///{source}", tmp_path / "backups")
    assert first["path"] != second["path"]
    assert Path(first["path"]).is_file() and Path(second["path"]).is_file()


def test_invalid_sqlite_source_does_not_leave_a_false_backup(tmp_path):
    source = tmp_path / "corrupt.db"
    original = b"not a SQLite database"
    source.write_bytes(original)
    with pytest.raises(sqlite3.DatabaseError):
        _backup(f"sqlite:///{source}", tmp_path / "backups")
    assert source.read_bytes() == original
    assert not list((tmp_path / "backups").glob("*.db"))


def test_downgrade_cannot_bypass_required_backup_with_skip_flag(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["migrate.py", "downgrade", "--skip-backup"])

    def forbidden_downgrade(*args, **kwargs):
        raise AssertionError("A downgrade without its required backup must never run")

    monkeypatch.setattr("scripts.migrate.command.downgrade", forbidden_downgrade)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "--skip-backup is not permitted for downgrade" in capsys.readouterr().err
