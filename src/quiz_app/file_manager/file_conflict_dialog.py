"""Wybór sposobu kopiowania istniejącego pliku pytania lub materiału."""

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class FileConflictDialog(QDialog):
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plik już istnieje")
        self.selected_action = "cancel"
        layout = QVBoxLayout(self)
        label = QLabel(f"Plik już istnieje: {file_path}")
        label.setWordWrap(True)
        layout.addWidget(label)
        buttons = QHBoxLayout()
        for text, action in (
            ("Nadpisz", "overwrite"),
            ("Pomiń", "skip"),
            ("Zachowaj oba", "rename"),
            ("Anuluj", "cancel"),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, value=action: self.choose(value))
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def choose(self, action):
        self.selected_action = action
        self.accept()
