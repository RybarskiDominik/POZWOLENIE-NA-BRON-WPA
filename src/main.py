"""Uruchomienie: python src/main.py [--database PLIK]."""

import argparse
import sqlite3
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from quiz_app.database import DATABASE_PATH, Database
from quiz_app.initial_import import import_on_first_start
from quiz_app.paths import APP_NAME, APP_VERSION
from quiz_app.ui.main_window import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--database", type=Path, default=DATABASE_PATH)
    arguments = parser.parse_args()
    app = QApplication(sys.argv)
    app.setOrganizationName("Nauka")
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    app.setStyleSheet("""
        QWidget { font-size: 14px; }
        QPushButton, QComboBox { padding: 10px 14px; }
        QLabel#title { font-size: 26px; font-weight: 600; }
        QLabel#question { font-size: 19px; padding: 12px 0; }
        QProgressBar { min-height: 18px; }
        QProgressBar::chunk { background-color: #1976d2; }
    """)
    try:
        database = Database(arguments.database)
        import_on_first_start(database)
        window = MainWindow(database)
    except (OSError, ValueError, sqlite3.Error) as error:
        QMessageBox.critical(None, "Nie można wczytać danych aplikacji", str(error))
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
