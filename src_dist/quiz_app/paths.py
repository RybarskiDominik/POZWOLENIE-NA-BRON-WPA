"""Ścieżki aplikacji uruchamianej z kodu lub z zainstalowanego EXE."""

import os
import sys
from pathlib import Path

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
    APP_DIRECTORY = Path(__file__).resolve().parents[1]
    DATA_DIRECTORY = APP_DIRECTORY

DATABASE_PATH = DATA_DIRECTORY / "database.sqlite3"
QUESTIONS_DIRECTORY = APP_DIRECTORY / "questions"
MATERIALS_DIRECTORY = APP_DIRECTORY / "materialy"
SCHEMA_PATH = APP_DIRECTORY / "quiz_app" / "schema.sql"
