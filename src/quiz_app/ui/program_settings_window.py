"""Ustawienia nauki, lokalizacje plików oraz kopie danych programu."""

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from ..file_manager.constans import DB_FILE


class ProgramSettingsWindow(QDialog):
    def __init__(self, file_manager, parent):
        super().__init__(parent, Qt.WindowType.Window)
        self.fm = file_manager
        self.main_window = parent
        self.setWindowTitle("Ustawienia programu")
        self.resize(800, 440)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        learning = QWidget()
        learning_layout = QVBoxLayout(learning)
        self.sheet_label = QLabel()
        self.sheet_label.setWordWrap(True)
        learning_layout.addWidget(self.sheet_label)
        self.shuffle_answers = parent.shuffle_answers
        learning_layout.addWidget(self.shuffle_answers)
        self.reset_statistics_button = QPushButton("Resetuj statystyki")
        self.reset_statistics_button.setToolTip(
            "Resetuje wyniki wybranego arkusza. Zachowuje quiz, ustawienia, "
            "listę problematycznych pytań, oznaczenia trudne i cykle."
        )
        self.reset_pool_button = QPushButton("Resetuj pulę pytań")
        self.reset_pool_button.setToolTip(
            "Odblokowuje pytania we wszystkich zestawach wybranego arkusza. "
            "Zachowuje wyniki, oznaczenia i bieżący quiz."
        )
        self.reset_statistics_button.clicked.connect(parent.reset_sheet_statistics)
        self.reset_pool_button.clicked.connect(parent.reset_sheet_pool)
        learning_layout.addWidget(self.reset_statistics_button)
        learning_layout.addWidget(self.reset_pool_button)
        learning_layout.addStretch()
        tabs.addTab(learning, "Nauka")

        files = QWidget()
        files_layout = QVBoxLayout(files)
        description = QLabel(
            "Lokalizacje są zapamiętywane. Wybierz folder, w którym znajduje się "
            "lub zostanie utworzona baza danych. Pytania i materiały są "
            "odczytywane ze wskazanych folderów."
        )
        description.setWordWrap(True)
        files_layout.addWidget(description)
        form = QFormLayout()
        self.path_fields = {}
        for name, label in (
            ("database", "Folder bazy danych"),
            ("questions", "Pytania JSON"),
            ("materials", "Materiały do nauki"),
        ):
            row = QHBoxLayout()
            field = QLineEdit()
            field.setReadOnly(True)
            field.setAccessibleName(label)
            self.path_fields[name] = field
            row.addWidget(field, 1)
            choose = QPushButton("Wybierz…")
            choose.clicked.connect(lambda checked=False, key=name: self.choose_path(key))
            row.addWidget(choose)
            reset = QPushButton("Domyślna")
            reset.clicked.connect(lambda checked=False, key=name: self.run(lambda: self.set_path(key, self.fm.defaults[key])))
            row.addWidget(reset)
            form.addRow(label, row)
        files_layout.addLayout(form)
        reset_paths = QPushButton("Przywróć domyślne lokalizacje")
        reset_paths.clicked.connect(lambda: self.run(self.reset_paths))
        files_layout.addWidget(reset_paths)
        backup_group = QGroupBox("Kopie zapasowe")
        backup_layout = QVBoxLayout(backup_group)
        backup_description = QLabel(
            "Kopia obejmuje bazę z postępami, pytania i materiały. Przywracanie "
            "zastępuje bazę oraz pliki o tych samych nazwach. Pozostałe pliki "
            "w folderach pytań i materiałów zostają zachowane."
        )
        backup_description.setWordWrap(True)
        backup_layout.addWidget(backup_description)
        backup_buttons = QHBoxLayout()
        backup = QPushButton("Utwórz kopię…")
        backup.clicked.connect(lambda: self.run(self.backup))
        restore = QPushButton("Przywróć kopię…")
        restore.clicked.connect(lambda: self.run(self.restore))
        backup_buttons.addWidget(backup)
        backup_buttons.addWidget(restore)
        backup_layout.addLayout(backup_buttons)
        files_layout.addWidget(backup_group)
        files_layout.addStretch()
        tabs.addTab(files, "Pliki i kopie")
        close = QPushButton("Zamknij")
        close.clicked.connect(self.close)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        self.refresh()

    def refresh(self):
        window = self.main_window
        self.sheet_label.setText(
            f"Ustawienia arkusza: {window.sheet_selector.currentText()}"
            if window.sheet_id is not None else "Zaimportuj arkusz, aby zmienić ustawienia nauki."
        )
        for button in (self.reset_statistics_button, self.reset_pool_button):
            button.setEnabled(window.sheet_id is not None)
        for name, path in (
            ("database", self.fm.database_path.parent),
            ("questions", self.fm.questions_directory),
            ("materials", self.fm.materials_directory),
        ):
            self.path_fields[name].setText(str(path))
            self.path_fields[name].setToolTip(str(path))

    def run(self, action):
        try:
            action()
        except (OSError, ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "Nie można zmienić ustawień", str(error))
        finally:
            self.refresh()

    def choose_path(self, name):
        current = self.path_fields[name].text()
        title = "Wybierz folder bazy danych" if name == "database" else "Wybierz folder"
        folder = QFileDialog.getExistingDirectory(self, title, current)
        if folder:
            path = Path(folder) / DB_FILE if name == "database" else Path(folder)
            self.run(lambda: self.set_path(name, path))

    def set_path(self, name, path):
        if name == "database":
            self.main_window.switch_database(path)
        else:
            self.fm.set_path(name, path)
            if name == "materials":
                self.main_window.close_study_window()

    def reset_paths(self):
        for name in ("questions", "materials", "database"):
            self.set_path(name, self.fm.defaults[name])

    def backup(self):
        folder = QFileDialog.getExistingDirectory(self, "Wybierz folder na kopię zapasową")
        if not folder or not self.main_window.save_current():
            self.main_window.resume_timer()
            return
        try:
            paths = self.fm.backup_workspace(Path(folder))
            QMessageBox.information(self, "Utworzono kopię", str(next(iter(paths.values())).parent))
        finally:
            self.main_window.resume_timer()

    def restore(self):
        folder = QFileDialog.getExistingDirectory(self, "Wybierz folder kopii zapasowej")
        if not folder:
            return
        if QMessageBox.question(
            self, "Przywróć kopię", "Zastąpić postępy i pliki danymi z kopii? "
            "Przed przywróceniem program zapisze kopię obecnych danych."
        ) != QMessageBox.StandardButton.Yes:
            return
        if not self.main_window.save_current():
            self.main_window.resume_timer()
            return
        window = self.main_window
        window.autosave_timer.stop()
        try:
            safety_copy = self.fm.backup_workspace()
            window.close_study_window()
            self.fm.restore_backup(Path(folder))
            window.refresh_database()
            QMessageBox.information(
                self, "Przywrócono kopię", "Wczytano dane. Kopia poprzednich danych: "
                + str(next(iter(safety_copy.values())).parent)
            )
        finally:
            window.autosave_timer.start()
            window.resume_timer()
