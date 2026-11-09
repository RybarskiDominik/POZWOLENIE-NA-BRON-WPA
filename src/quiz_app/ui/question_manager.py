"""Import arkuszy, ich zestawów i objaśnień oraz przeglądanie pytań."""

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ..catalog import import_explanations, import_question_sets, import_questions
from ..importers import prepare_explanations, prepare_question_sets, preview_import
from ..file_manager.file_manager import QUESTIONS_DIRECTORY
from ..study import load_settings, save_settings
from .question_view import highlight_difficult_questions, show_question_details


class QuestionManager(QDialog):
    def __init__(self, catalog, sheet_id=None, set_id=None, parent=None, *, questions_directory=QUESTIONS_DIRECTORY):
        super().__init__(parent)
        self.catalog = catalog
        self.questions_directory = Path(questions_directory)
        self.setWindowTitle("Pytania i zestawy")
        self.resize(950, 650)
        layout = QVBoxLayout(self)
        selection = QFormLayout()
        self.sheet_selector = QComboBox()
        self.set_selector = QComboBox()
        selection.addRow("Arkusz", self.sheet_selector)
        selection.addRow("Zestaw", self.set_selector)
        layout.addLayout(selection)
        imports = QHBoxLayout()
        self.import_questions_button = QPushButton("Importuj arkusz JSON…")
        self.import_sets_button = QPushButton("Importuj zestawy JSON…")
        self.import_explanations_button = QPushButton("Importuj objaśnienia JSON…")
        self.import_questions_button.clicked.connect(
            lambda: self.run(self.import_sheet)
        )
        self.import_sets_button.clicked.connect(lambda: self.run(self.import_sets))
        self.import_explanations_button.clicked.connect(
            lambda: self.run(self.import_explanations)
        )
        imports.addWidget(self.import_questions_button)
        imports.addWidget(self.import_sets_button)
        imports.addWidget(self.import_explanations_button)
        layout.addLayout(imports)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Szukaj numeru lub treści pytania…")
        search_row.addWidget(self.search, 1)
        self.difficult_button = QPushButton("Oznacz jako trudne")
        self.difficult_button.setEnabled(False)
        self.difficult_button.clicked.connect(lambda: self.run(self.toggle_difficult))
        search_row.addWidget(self.difficult_button)
        layout.addLayout(search_row)
        self.questions = QListWidget()
        self.questions.setWordWrap(True)
        layout.addWidget(self.questions, 2)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText(
            "Wybierz pytanie, aby zobaczyć podstawę prawną i odpowiedzi."
        )
        layout.addWidget(self.details, 1)
        actions = QHBoxLayout()
        self.delete_sheet_button = QPushButton("Usuń arkusz…")
        self.delete_sets_button = QPushButton("Usuń zestawy dla arkusza…")
        self.delete_explanations_button = QPushButton("Usuń objaśnienia dla arkusza…")
        self.delete_sheet_button.clicked.connect(lambda: self.run(self.delete_sheet))
        self.delete_sets_button.clicked.connect(
            lambda: self.run(self.delete_sheet_sets)
        )
        self.delete_explanations_button.clicked.connect(
            lambda: self.run(self.delete_sheet_explanations)
        )
        actions.addWidget(self.delete_sheet_button)
        actions.addWidget(self.delete_sets_button)
        actions.addWidget(self.delete_explanations_button)
        layout.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Zamknij")
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)
        self.sheet_selector.currentIndexChanged.connect(lambda: self.reload_sets())
        self.set_selector.currentIndexChanged.connect(
            lambda: self.run(self.selection_changed)
        )
        self.search.textChanged.connect(self.filter_questions)
        self.questions.currentItemChanged.connect(self.show_details)
        self.questions.itemSelectionChanged.connect(self.update_difficult_button)
        self.refresh_sheets(sheet_id, set_id)

    def run(self, action):
        try:
            action()
        except (OSError, ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "Nie można wykonać operacji", str(error))

    def refresh_sheets(self, sheet_id=None, set_id=None):
        self.sheet_selector.blockSignals(True)
        self.sheet_selector.clear()
        for identifier, name in self.catalog.sheets():
            self.sheet_selector.addItem(name, identifier)
        index = self.sheet_selector.findData(sheet_id)
        self.sheet_selector.setCurrentIndex(index if index >= 0 else 0)
        self.sheet_selector.setEnabled(self.sheet_selector.count() > 0)
        self.sheet_selector.blockSignals(False)
        self.reload_sets(set_id)

    def reload_sets(self, set_id=None):
        self.search.clear()
        sheet_id = self.sheet_selector.currentData()
        if sheet_id is not None and set_id is None:
            settings = load_settings(self.catalog.database, sheet_id)
            set_id = settings.set_id
        self.set_selector.blockSignals(True)
        self.set_selector.clear()
        for identifier, name in self.catalog.sets(sheet_id):
            self.set_selector.addItem(name, identifier)
        index = self.set_selector.findData(set_id)
        self.set_selector.setCurrentIndex(index if index >= 0 else 0)
        self.set_selector.blockSignals(False)
        self.selection_changed()

    def selection_changed(self):
        sheet_id = self.sheet_selector.currentData()
        if sheet_id is not None:
            settings = load_settings(self.catalog.database, sheet_id)
            settings.set_id = self.set_selector.currentData()
            save_settings(self.catalog.database, settings)
        self.show_questions()

    def show_questions(self):
        sheet_id = self.sheet_selector.currentData()
        set_id = self.set_selector.currentData()
        has_sheet = sheet_id is not None
        self.set_selector.setEnabled(has_sheet)
        self.import_sets_button.setEnabled(has_sheet)
        self.import_explanations_button.setEnabled(has_sheet)
        self.delete_sheet_button.setEnabled(has_sheet)
        self.delete_sets_button.setEnabled(bool(self.catalog.custom_sets(sheet_id)))
        self.delete_explanations_button.setEnabled(has_sheet)
        self.flags = self.catalog.flags(sheet_id)
        self.questions.clear()
        for question in self.catalog.questions(sheet_id, set_id):
            item = QListWidgetItem(f"{question.number}. {question.text}")
            item.setData(Qt.ItemDataRole.UserRole, question)
            self.questions.addItem(item)
        highlight_difficult_questions(self.questions, self.flags)
        self.filter_questions()

    def show_details(self, item):
        question = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        show_question_details(self.details, question)
        self.update_difficult_button()

    def selected_question(self):
        item = self.questions.currentItem()
        if item is None or item.isHidden() or not item.isSelected():
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def update_difficult_button(self):
        question = self.selected_question()
        self.difficult_button.setEnabled(question is not None)
        difficult = False
        if question is not None:
            difficult = bool(self.flags[question.question_id]["is_difficult"])
        self.difficult_button.setText(
            "Usuń oznaczenie „Trudne”" if difficult else "Oznacz jako trudne"
        )

    def toggle_difficult(self):
        question = self.selected_question()
        if question is None:
            return
        self.catalog.toggle_difficult(question.sheet_id, question.question_id)
        self.show_questions()
        for index in range(self.questions.count()):
            item = self.questions.item(index)
            candidate = item.data(Qt.ItemDataRole.UserRole)
            if not item.isHidden() and candidate.question_id == question.question_id:
                self.questions.setCurrentItem(item)
                break

    def filter_questions(self):
        text = self.search.text().strip().casefold()
        for i in range(self.questions.count()):
            item = self.questions.item(i)
            item.setHidden(text not in item.text().casefold())
            if item.isHidden():
                item.setSelected(False)
                if item is self.questions.currentItem():
                    self.questions.setCurrentRow(-1)
        self.update_difficult_button()

    def choose_file(self, title, initial_path=None):
        filename, _ = QFileDialog.getOpenFileName(
            self, title, str(initial_path or self.questions_directory), "JSON (*.json)"
        )
        return Path(filename) if filename else None

    def confirm(self, title, message):
        return (
            QMessageBox.question(self, title, message) == QMessageBox.StandardButton.Yes
        )

    def import_sheet(self):
        path = self.choose_file("Wybierz arkusz pytań JSON")
        if path is None:
            return
        preview = preview_import(path)
        if not self.confirm(
            "Import arkusza",
            f"{preview.name}\nPytań: {len(preview.questions)}\nImportować arkusz?",
        ):
            return
        existing_ids = {identifier for identifier, _ in self.catalog.sheets()}
        sheet_id = import_questions(self.catalog.database, preview)
        self.refresh_sheets(sheet_id)
        message = (
            "Arkusz o tej nazwie i treści już istnieje. Wybrano istniejący arkusz."
            if sheet_id in existing_ids
            else f"Dodano arkusz „{preview.name}”. Pytań: {len(preview.questions)}."
        )
        QMessageBox.information(self, "Import arkusza", message)

    def sheet_questions(self):
        sheet_id = self.sheet_selector.currentData()
        if sheet_id is None:
            raise ValueError("Wybierz arkusz źródłowy.")
        return self.catalog.questions(sheet_id)

    def import_sets(self):
        questions = self.sheet_questions()
        path = self.choose_file("Wybierz plik zestawów")
        if path is None:
            return
        prepared = prepare_question_sets(path, questions)
        lines = [
            f"Arkusz: {self.sheet_selector.currentText()}",
            f"Zestawów: {len(prepared)}",
        ]
        lines.extend(f"{name}: {len(ids)} pytań" for name, ids in prepared[:10])
        lines.append("Importować zestawy do wybranego arkusza?")
        if not self.confirm("Import zestawów", "\n".join(lines)):
            return
        set_ids, skipped = import_question_sets(
            self.catalog.database, self.sheet_selector.currentData(), prepared
        )
        self.reload_sets(set_ids[0])
        QMessageBox.information(
            self,
            "Import zakończony",
            f"Dodano: {len(set_ids) - skipped}. Pominięto identyczne: {skipped}.",
        )

    def import_explanations(self):
        questions = self.sheet_questions()
        path = self.choose_file(
            "Wybierz plik objaśnień",
            self.questions_directory / "egzamin_na_broń_WPA_200_podstawy_prawne.json",
        )
        if path is None:
            return
        prepared = prepare_explanations(path, questions)
        if self.confirm(
            "Import objaśnień",
            f"Zapisać objaśnienia dla {len(prepared)} pytań? "
            "Wskazane objaśnienia zostaną zastąpione.",
        ):
            import_explanations(self.catalog.database, prepared)
            self.show_questions()

    def delete_sheet(self):
        sheet_id = self.sheet_selector.currentData()
        if sheet_id is not None and self.confirm(
            "Usuń arkusz",
            f"Usunąć arkusz „{self.sheet_selector.currentText()}”, "
            "jego pytania, zestawy, objaśnienia, ustawienia oraz wszystkie "
            "podejścia i wyniki tego arkusza?",
        ):
            self.catalog.delete_sheet(sheet_id)
            self.refresh_sheets()

    def delete_sheet_sets(self):
        sheet_id = self.sheet_selector.currentData()
        if sheet_id is not None and self.confirm(
            "Usuń zestawy arkusza",
            f"Usunąć wszystkie zestawy arkusza „{self.sheet_selector.currentText()}”? "
            "Zapisane podejścia i wyniki pozostaną.",
        ):
            self.catalog.delete_sets(sheet_id)
            self.reload_sets()

    def delete_sheet_explanations(self):
        sheet_id = self.sheet_selector.currentData()
        if sheet_id is not None and self.confirm(
            "Usuń objaśnienia arkusza",
            f"Usunąć objaśnienia pytań arkusza „{self.sheet_selector.currentText()}”? "
            "Zapisane podejścia zachowają kopie objaśnień.",
        ):
            self.catalog.delete_explanations(sheet_id)
            self.show_questions()
