"""Uruchomienie: python src/main.py [--database PLIK]."""

import argparse
import sqlite3
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from quiz_app.database import Database
from quiz_app.initial_import import import_on_first_start
from quiz_app.file_manager.file_manager import APP_NAME, APP_VERSION, FileManager
from quiz_app.ui.main_window import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--database", type=Path)
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
        file_manager = FileManager(database_path=arguments.database)
        database = Database(file_manager.database_path)
        import_on_first_start(database, file_manager.questions_directory)
        window = MainWindow(database, file_manager)
    except (OSError, ValueError, sqlite3.Error) as error:
        QMessageBox.critical(None, "Nie można wczytać danych aplikacji", str(error))
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
