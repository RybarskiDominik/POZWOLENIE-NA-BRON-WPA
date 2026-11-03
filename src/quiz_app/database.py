"""Połączenia i automatyczna aktualizacja jednej lokalnej bazy SQLite."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .migrations import APPLICATION_ID, SCHEMA_VERSION, update_database
from .paths import DATABASE_PATH

__all__ = ["APPLICATION_ID", "DATABASE_PATH", "SCHEMA_VERSION", "Database"]


class Database:
    def __init__(self, path: Path = DATABASE_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            update_database(connection, self.path)

    @contextmanager
    def connect(self, existing_connection=None):
        """Nowe połączenie zapisuje lub wycofuje zmiany, a następnie się zamyka.

        Przekazane połączenie pozostaje pod kontrolą wywołującego.
        """
        if existing_connection is not None:
            yield existing_connection
            return

        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()
