from scripts.migrate import _backup


def test_postgres_backup_instruction_never_contains_credentials(tmp_path):
    database_url = "postgresql+psycopg://owner:top-secret@db.internal/creatorproof"
    evidence = _backup(database_url, tmp_path)

    assert evidence["performed"] is False
    assert "$CREATORPROOF_DATABASE_URL" in evidence["required_command"]
    assert database_url not in str(evidence)
    assert "top-secret" not in str(evidence)
