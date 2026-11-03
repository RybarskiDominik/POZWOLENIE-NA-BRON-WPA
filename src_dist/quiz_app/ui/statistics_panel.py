"""Wyniki arkusza, statystyki pytań, oznaczenia trudności i aktywność."""

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..statistics import load_statistics


class StatisticsPanel(QDialog):
    def __init__(self, database, catalog, sheet_id, set_id=None, parent=None):
        super().__init__(parent)
        self.database = database
        self.catalog = catalog
        self.sheet_id = sheet_id
        self.set_id = set_id
        sheet_name = dict(catalog.sheets()).get(sheet_id, "")
        self.setWindowTitle(f"Statystyki — {sheet_name}")
        self.resize(1100, 700)
        layout = QVBoxLayout(self)
        self.current = QLabel()
        self.summary = QLabel()
        for label in (self.current, self.summary):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(label)
        tabs = QTabWidget()
        self.history = QListWidget()
        self.history.setWordWrap(True)
        tabs.addTab(self.history, "Podejścia")
        details = QWidget()
        details_layout = QVBoxLayout(details)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Szukaj po numerze lub treści pytania")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_questions)
        details_layout.addWidget(self.search)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            [
                "Nr",
                "Pytanie",
                "Przerobione",
                "Poprawne",
                "Błędy",
                "Błędy (%)",
                "Poprawne (%)",
                "Śr. czas (s)",
                "Trudne",
            ]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeaderItem(7).setToolTip(
            "Do 5 ostatnich odpowiedzi na to pytanie. Od 2 pomiarów pomijamy "
            "jeden najdłuższy czas. Jeden pomiar pokazujemy bez odrzucania."
        )
        self.table.itemSelectionChanged.connect(self.update_difficult_button)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        details_layout.addWidget(self.table)
        self.difficult_button = QPushButton("Oznacz jako trudne")
        self.difficult_button.clicked.connect(self.toggle_difficult)
        details_layout.addWidget(self.difficult_button)
        note = QLabel(
            "Przerobione = zatwierdzone odpowiedzi, także z przerwanych podejść. "
            "Średni czas: do 5 ostatnich odpowiedzi, bez jednego najdłuższego "
            "pomiaru. W tabeli liczymy go osobno dla każdego pytania."
        )
        note.setWordWrap(True)
        details_layout.addWidget(note)
        tabs.addTab(details, "Pytania")
        self.activity = QListWidget()
        tabs.addTab(self.activity, "Aktywność")
        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Zamknij")
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self):
        selected_id = self.selected_question_id()
        report = load_statistics(self.database, self.sheet_id, self.set_id)
        questions = self.catalog.questions(self.sheet_id, self.set_id)
        self.flags = self.catalog.flags(self.sheet_id)
        self.show_summary(report, questions)
        self.show_history(report["history"])
        self.show_question_statistics(questions, report["questions"], selected_id)
        self.show_activity(report["days"])

    def show_summary(self, report, questions):
        attempts = report["attempts"]
        accuracy = report["correct"] / attempts * 100 if attempts else 0
        covered = sum(q.question_id in report["questions"] for q in questions)
        coverage = covered / len(questions) * 100 if questions else 0
        average = report["average_seconds"]
        average_text = f"{average:.2f} s" if average is not None else "—"
        completed = [
            entry for entry in report["history"] if entry["status"] == "completed"
        ]
        completed_answers = sum(entry["answered"] for entry in completed)
        completed_correct = sum(entry["correct"] for entry in completed)
        if completed_answers:
            completed_accuracy = completed_correct / completed_answers * 100
            completed_text = (
                f"Ukończone podejścia: {len(completed)} · Poprawne w nich: "
                f"{completed_correct} / {completed_answers} "
                f"({completed_accuracy:.1f}%)"
            )
        else:
            completed_text = "Nie ukończono jeszcze żadnego podejścia."
        self.summary.setText(
            f"Przerobione pytania: {covered} / {len(questions)} ({coverage:.1f}%)\n"
            f"Odpowiedzi: {attempts} · Poprawne: {report['correct']} ({accuracy:.1f}%) "
            f"· Błędy: {report['errors']} · Średni czas: {average_text}\n"
            f"Problematyczne w arkuszu: {report['problems']} "
            f"· Oznaczone jako trudne: {report['difficult']}\n{completed_text}"
        )
        current = report["current"]
        if current:
            current_text = (
                f"Bieżące / ostatnie podejście: {current['title']}\n"
                f"Odpowiedzi: {current['answered']} / {current['total']} "
                f"· Poprawne: {current['correct']} "
                f"· Błędy: {current['answered'] - current['correct']}"
            )
        else:
            current_text = "Brak zapisanego podejścia tego arkusza."
        self.current.setText(current_text)

    def show_history(self, history):
        self.history.clear()
        statuses = {
            "active": "w toku",
            "completed": "ukończono",
            "cancelled": "przerwano",
        }
        for entry in history:
            minutes, seconds = divmod(int(entry["elapsed_seconds"]), 60)
            self.history.addItem(
                f"{entry['started_at'][:16].replace('T', ' ')} UTC · {entry['title']} "
                f"· {entry['mode']} · Poprawne: "
                f"{entry['correct']} / {entry['answered']} "
                f"· {minutes}:{seconds:02d} · {statuses[entry['status']]}"
            )

    def show_question_statistics(self, questions, question_statistics, selected_id):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(questions))
        for row, question in enumerate(questions):
            counts = question_statistics.get(question.question_id, {})
            answered = counts.get("attempts", 0)
            correct = counts.get("correct", 0)
            errors = answered - correct
            average = counts.get("average_seconds")
            flags = self.flags[question.question_id]
            values = [
                question.number,
                question.text,
                answered,
                correct,
                errors,
                round(errors / answered * 100, 1) if answered else "—",
                round(correct / answered * 100, 1) if answered else "—",
                round(average, 2) if average is not None else "—",
                "Tak" if flags["is_difficult"] else "—",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem()
                item.setData(Qt.ItemDataRole.DisplayRole, value)
                item.setData(Qt.ItemDataRole.UserRole, question.question_id)
                if column == 1:
                    item.setToolTip(question.text)
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)
        self.table.clearSelection()
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == selected_id:
                self.table.selectRow(row)
                break
        self.filter_questions()

    def show_activity(self, days):
        self.activity.clear()
        for day in days:
            accuracy = day["correct"] / day["attempts"] * 100
            self.activity.addItem(
                f"{day['day']} UTC · Odpowiedzi: {day['attempts']} "
                f"· Poprawne: {accuracy:.1f}%"
            )

    def filter_questions(self):
        query = self.search.text().strip().casefold()
        for row in range(self.table.rowCount()):
            number = self.table.item(row, 0).text()
            text = self.table.item(row, 1).text().casefold()
            matches = query == number if query.isdecimal() else query in text
            self.table.setRowHidden(row, not matches)
        self.update_difficult_button()

    def selected_question_id(self):
        row = self.table.currentRow()
        if row < 0 or self.table.isRowHidden(row) or not self.table.selectedItems():
            return None
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def update_difficult_button(self):
        question_id = self.selected_question_id()
        self.difficult_button.setEnabled(question_id is not None)
        difficult = question_id is not None and self.flags[question_id]["is_difficult"]
        self.difficult_button.setText(
            "Usuń oznaczenie „Trudne”" if difficult else "Oznacz jako trudne"
        )

    def toggle_difficult(self):
        question_id = self.selected_question_id()
        if question_id is None:
            return
        try:
            self.catalog.toggle_difficult(self.sheet_id, question_id)
        except (OSError, ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "Nie można zmienić oznaczenia", str(error))
            return
        self.refresh()
