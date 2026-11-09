"""Ścieżki, lokalizacje danych i kopie zapasowe aplikacji do nauki."""

import os
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

from .constans import BACKUPS_FOLDER_NAME, DB_FILE, MATERIALS_FOLDER_NAME, QUESTIONS_FOLDER_NAME

APP_NAME = "Pozwolenie na broń"
APP_VERSION = "1.0.0.0"

if getattr(sys, "frozen", False):
    APP_DIRECTORY = Path(sys.executable).resolve().parent
    DATA_DIRECTORY = (
        Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        / "PozwolenieNaBron"
        / "data"
    )
else:
    APP_DIRECTORY = Path(__file__).resolve().parents[2]
    DATA_DIRECTORY = APP_DIRECTORY

DATABASE_PATH = DATA_DIRECTORY / DB_FILE
QUESTIONS_DIRECTORY = APP_DIRECTORY / QUESTIONS_FOLDER_NAME
MATERIALS_DIRECTORY = APP_DIRECTORY / MATERIALS_FOLDER_NAME
SCHEMA_PATH = APP_DIRECTORY / "quiz_app" / "schema.sql"
UI_DIRECTORY = APP_DIRECTORY / "quiz_app" / "ui"


def backup_database(source, destination):
    """Kopia SQLite obejmuje również zatwierdzone dane z pliku WAL."""
    with (
        closing(sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True)) as original,
        closing(sqlite3.connect(destination)) as backup,
    ):
        original.backup(backup)


class FileManager:
    def __init__(self, *, settings=None, database_path=None, app_directory=None, data_directory=None):
        # Import samych stałych pozostaje dostępny także dla wersji web bez Qt.
        if settings is None:
            from PySide6.QtCore import QSettings

            settings = QSettings("Nauka", APP_NAME)
        self.settings = settings
        self.app_directory = Path(app_directory or APP_DIRECTORY).resolve()
        self.data_directory = Path(data_directory or DATA_DIRECTORY).resolve()
        self.defaults = {
            "database": self.data_directory / DB_FILE,
            "questions": self.app_directory / QUESTIONS_FOLDER_NAME,
            "materials": self.app_directory / MATERIALS_FOLDER_NAME,
        }
        self._paths = {
            name: Path(settings.value(f"paths/{name}", str(default), type=str)).expanduser().resolve()
            for name, default in self.defaults.items()
        }
        if database_path is not None:
            self._paths["database"] = Path(database_path).expanduser().resolve()

    @property
    def database_path(self):
        return self._paths["database"]

    @property
    def questions_directory(self):
        return self._paths["questions"]

    @property
    def materials_directory(self):
        return self._paths["materials"]

    def set_path(self, name, path):
        if name not in self.defaults:
            raise ValueError(f"Nieznana lokalizacja: {name}")
        if not str(path).strip():
            raise ValueError("Ścieżka nie może być pusta.")
        path = Path(path).expanduser().resolve()
        if name == "database":
            if path.is_dir():
                raise ValueError("Wskaż plik bazy SQLite.")
            path.parent.mkdir(parents=True, exist_ok=True)
        elif not path.is_dir() and path != self.defaults[name]:
            raise ValueError(f"Folder nie istnieje: {path}")
        self.settings.setValue(f"paths/{name}", str(path))
        self.settings.sync()
        if self.settings.status() != self.settings.Status.NoError:
            raise OSError("Nie udało się zapisać lokalizacji w ustawieniach programu.")
        self._paths[name] = path

    def backup_workspace(self, backup_root=None):
        root = Path(backup_root or self.data_directory / BACKUPS_FOLDER_NAME).resolve()
        for source in (self.questions_directory, self.materials_directory):
            if root.is_relative_to(source):
                raise ValueError("Kopia zapasowa musi znajdować się poza folderami pytań i materiałów.")
        root.mkdir(parents=True, exist_ok=True)
        destination = Path(tempfile.mkdtemp(prefix=datetime.now().strftime("Backup_%Y-%m-%d_%H-%M-%S_"), dir=root))
        paths = {}
        try:
            if self.database_path.is_file():
                target = destination / DB_FILE
                backup_database(self.database_path, target)
                paths["Baza danych"] = target
            for label, folder, source in (
                ("Pytania", QUESTIONS_FOLDER_NAME, self.questions_directory),
                ("Materiały", MATERIALS_FOLDER_NAME, self.materials_directory),
            ):
                if source.is_dir():
                    target = destination / folder
                    shutil.copytree(source, target)
                    paths[label] = target
            if not paths:
                raise ValueError("Brak danych do zapisania w kopii zapasowej.")
        except BaseException:
            # Usuwamy wyłącznie nowy katalog utworzony przez tę operację.
            shutil.rmtree(destination)
            raise
        return paths

    def restore_backup(self, backup_path):
        """Sprawdź bazę przed przywróceniem; materiały scalaj bez kasowania folderów."""
        from ..database import APPLICATION_ID, Database

        backup_path = Path(backup_path).resolve()
        source_database = backup_path / DB_FILE
        if not source_database.is_file():
            raise ValueError(f"Kopia nie zawiera bazy danych {DB_FILE}.")
        for source, destination in (
            (backup_path / QUESTIONS_FOLDER_NAME, self.questions_directory),
            (backup_path / MATERIALS_FOLDER_NAME, self.materials_directory),
        ):
            if source.is_dir() and (source.is_relative_to(destination) or destination.is_relative_to(source)):
                raise ValueError("Folder kopii zapasowej koliduje z folderem docelowym.")
        with tempfile.TemporaryDirectory() as temporary:
            staged = Path(temporary) / DB_FILE
            backup_database(source_database, staged)
            with closing(sqlite3.connect(staged)) as connection:
                if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                    raise ValueError("Kopia nie zawiera bazy danych tego programu.")
                if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("Baza danych w kopii jest uszkodzona.")
            Database(staged)  # Odrzuca obce/uszkodzone bazy i wykonuje migracje na kopii.
            restored = {}
            for label, folder, destination in (
                ("Pytania", QUESTIONS_FOLDER_NAME, self.questions_directory),
                ("Materiały", MATERIALS_FOLDER_NAME, self.materials_directory),
            ):
                source = backup_path / folder
                if source.is_dir():
                    shutil.copytree(source, destination, dirs_exist_ok=True)
                    restored[label] = destination
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            backup_database(staged, self.database_path)
            restored["Baza danych"] = self.database_path
        return restored
