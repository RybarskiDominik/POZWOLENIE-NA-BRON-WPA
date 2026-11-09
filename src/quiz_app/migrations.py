"""Schemat startowy to wersja 0; kolejne migracje dopisujemy do MIGRATIONS."""

import os
import sqlite3
import tempfile
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from .models import DEFAULT_SETS
from .file_manager.file_manager import SCHEMA_PATH

APPLICATION_ID = 0x51555A33
BASE_SCHEMA = SCHEMA_PATH


def _add_initial_import_flag(connection):
    connection.execute(
        "ALTER TABLE app_state ADD COLUMN initial_import_done "
        "INTEGER NOT NULL DEFAULT 0 CHECK (initial_import_done IN (0, 1))"
    )


def _add_high_error_rate_set(connection):
    connection.execute(
        "CREATE TABLE question_sets_new ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "sheet_id INTEGER NOT NULL REFERENCES sheets(id) ON DELETE CASCADE, "
        "name TEXT NOT NULL, "
        "kind TEXT NOT NULL DEFAULT 'custom' CHECK (kind IN "
        "('all', 'problems', 'problems_keep', 'difficult', "
        "'high_error_rate', 'custom')), "
        "UNIQUE (id, sheet_id))"
    )
    connection.execute("INSERT INTO question_sets_new SELECT * FROM question_sets")
    connection.execute("DROP TABLE question_sets")
    connection.execute("ALTER TABLE question_sets_new RENAME TO question_sets")
    connection.execute("CREATE INDEX sets_by_sheet ON question_sets(sheet_id, name)")
    connection.execute(
        "CREATE UNIQUE INDEX default_set_per_sheet ON question_sets(sheet_id, kind) "
        "WHERE kind != 'custom'"
    )
    connection.execute(
        "INSERT INTO question_sets(sheet_id, name, kind) "
        "SELECT id, ?, 'high_error_rate' FROM sheets",
        (DEFAULT_SETS["high_error_rate"],),
    )


def _rename_high_error_rate_set(connection):
    connection.execute(
        "UPDATE question_sets SET name = ? WHERE kind = 'high_error_rate'",
        (DEFAULT_SETS["high_error_rate"],),
    )


def _add_error_rate_threshold(connection):
    connection.execute(
        "ALTER TABLE sheets ADD COLUMN error_rate_threshold "
        "INTEGER NOT NULL DEFAULT 15 CHECK (error_rate_threshold BETWEEN 0 AND 100)"
    )
    _rename_high_error_rate_set(connection)


# Element 0 aktualizuje wersję 0 do 1, element 1 wersję 1 do 2 itd.
# Migracja używa execute()/executemany(); nie wywołuje commit() ani executescript().
MIGRATIONS: tuple[Callable[[sqlite3.Connection], None], ...] = (
    _add_initial_import_flag,
    _add_high_error_rate_set,
    _rename_high_error_rate_set,
    _rename_high_error_rate_set,  # 3 → 4: nazwa uwzględnia również dokładnie 20%.
    _add_error_rate_threshold,
)
SCHEMA_VERSION = len(MIGRATIONS)


def _schema_objects(connection):
    return [
        (kind, name, " ".join(sql.split()))
        for kind, name, sql in connection.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY type, name"
        )
    ]


def _matches_baseline(objects):
    with closing(sqlite3.connect(":memory:")) as baseline:
        baseline.executescript(BASE_SCHEMA.read_text(encoding="utf-8"))
        return objects == _schema_objects(baseline)


def _create_backup(path):
    path = Path(path).resolve()
    descriptor, filename = tempfile.mkstemp(
        prefix=f"{path.stem}.backup-", suffix=".sqlite3", dir=path.parent
    )
    os.close(descriptor)
    try:
        with (
            closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(filename)) as backup,
        ):
            source.backup(backup)
    except BaseException:
        Path(filename).unlink(missing_ok=True)
        raise


def _create_baseline(connection):
    # executescript() zatwierdziłby trwającą transakcję, dlatego wykonujemy
    # kompletne instrukcje osobno i zachowujemy możliwość wycofania całości.
    statement = ""
    for line in BASE_SCHEMA.read_text(encoding="utf-8").splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        connection.execute(statement)


def _validate_migration_history(connection, current_version, latest_version):
    if current_version > latest_version:
        raise ValueError(
            "Baza danych pochodzi z nowszej wersji aplikacji. Zaktualizuj aplikację."
        )
    saved_versions = [
        row[0]
        for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
    ]
    expected_versions = list(range(current_version + 1))
    if saved_versions != expected_versions:
        raise ValueError("Historia migracji nie zgadza się z wersją bazy danych.")


def _register_baseline(connection):
    connection.execute(
        "CREATE TABLE schema_migrations ("
        "version INTEGER PRIMARY KEY CHECK (version >= 0), "
        "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    connection.execute("INSERT INTO schema_migrations(version) VALUES (0)")
    connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
    connection.execute("PRAGMA user_version = 0")


def _apply_updates(connection, path):
    application_id = connection.execute("PRAGMA application_id").fetchone()[0]
    current_version = connection.execute("PRAGMA user_version").fetchone()[0]
    schema_objects = _schema_objects(connection)
    has_migration_history = any(
        kind == "table" and name == "schema_migrations"
        for kind, name, _ in schema_objects
    )
    is_empty_database = (
        not schema_objects and application_id == 0 and current_version == 0
    )

    # Starszy kod oznaczał schemat startowy numerem 5. Rejestrujemy go jako 0.
    is_baseline_database = (
        not has_migration_history
        and application_id == APPLICATION_ID
        and current_version in (0, 5)
        and _matches_baseline(schema_objects)
    )
    needs_registration = is_empty_database or is_baseline_database
    latest_version = len(MIGRATIONS)

    if not needs_registration:
        if application_id != APPLICATION_ID or not has_migration_history:
            raise ValueError("Wybrany plik jest obcą lub nieobsługiwaną bazą danych.")
        _validate_migration_history(connection, current_version, latest_version)
        if current_version == latest_version:
            return

    if not is_empty_database:
        _create_backup(path)
    if is_empty_database:
        _create_baseline(connection)
    if needs_registration:
        _register_baseline(connection)
        current_version = 0

    for target_version in range(current_version + 1, latest_version + 1):
        migration = MIGRATIONS[target_version - 1]
        migration(connection)
        connection.execute(
            "INSERT INTO schema_migrations(version) VALUES (?)", (target_version,)
        )
        connection.execute(f"PRAGMA user_version = {target_version}")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("Migracja narusza powiązania między danymi. Zmiany wycofano.")


def update_database(connection, path):
    """Sprawdź bazę, zrób kopię i wykonaj brakujące migracje w jednej transakcji."""
    if connection.in_transaction:
        raise ValueError("Migracji nie można uruchomić w trwającej transakcji.")
    foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    # Kontrolę relacji wyłączamy przed transakcją i sprawdzamy je przed zapisem.
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            _apply_updates(connection, path)
    finally:
        connection.execute(f"PRAGMA foreign_keys = {foreign_keys}")
