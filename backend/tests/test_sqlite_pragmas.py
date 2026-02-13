import sqlite3

from app.models.database import SQLITE_BUSY_TIMEOUT_MS, _configure_sqlite_connection


def test_configure_sqlite_connection_sets_busy_timeout_and_wal(tmp_path) -> None:
    db_path = tmp_path / "pragma_test.db"
    connection = sqlite3.connect(db_path)
    try:
        _configure_sqlite_connection(connection, None)

        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]

        assert busy_timeout == SQLITE_BUSY_TIMEOUT_MS
        assert str(journal_mode).lower() == "wal"
        assert synchronous in (1, "1")  # NORMAL
    finally:
        connection.close()
