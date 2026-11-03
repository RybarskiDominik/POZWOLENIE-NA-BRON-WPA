"""Prosty ekran nauki. Każda odpowiedź jest zapisywana przed zmianą widoku."""

import sqlite3
from copy import deepcopy

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..catalog import ERROR_RATE_THRESHOLD_PERCENT, Catalog
from ..models import Settings
from ..paths import APP_NAME
from ..quiz import QuizSession
from ..study import (
    cancel_session,
    load_session,
    load_settings,
    reset_question_pool,
    reset_statistics,
    save_session,
    save_settings,
    unseen_questions,
)
from .question_manager import QuestionManager
from .quiz_page import QuizPage, text_label
from .statistics_panel import StatisticsPanel
from .study_window import StudyWindow


class MainWindow(QMainWindow):
    def __init__(self, database):
        super().__init__()
        self.database = database
        self.catalog = Catalog(database)
        settings = load_settings(database)
        self.sheet_id = None
        self.session = None
        self.study_window = None
        self.setWindowTitle(f"{APP_NAME} — pytania, quizy i testy")
        self.resize(1000, 720)
        self.setMinimumSize(760, 540)
        self.build_toolbar()
        self.pages = QStackedWidget()
        self.setCentralWidget(self.pages)
        self.build_home()
        self.build_quiz()
        self.build_result()
        self.build_status_bar()
        self.reload_sheets(settings.sheet_id)
        self.sheet_selector.currentIndexChanged.connect(self.sheet_changed)
        self.set_selector.currentIndexChanged.connect(self.preferences_changed)
        self.question_count.currentIndexChanged.connect(self.preferences_changed)
        self.mode.currentIndexChanged.connect(self.preferences_changed)
        self.shuffle_answers.toggled.connect(self.preferences_changed)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(5000)
        self.autosave_timer.timeout.connect(self.autosave)
        self.autosave_timer.start()

    def build_toolbar(self):
        toolbar = QToolBar("Nawigacja")
        toolbar.setMovable(False)
        toolbar.setStyleSheet("QToolBar { spacing: 0px; }")
        toolbar.addAction("Pytania i zestawy…", self.manage_questions)
        gap = QWidget()
        gap.setFixedWidth(10)
        toolbar.addWidget(gap)
        self.study_action = toolbar.addAction("Nauka", self.show_study)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        self.statistics_action = toolbar.addAction("Statystyki…", self.show_statistics)
        self.addToolBar(toolbar)

    def build_home(self):
        self.home_page = QWidget()
        layout = QVBoxLayout(self.home_page)
        layout.setContentsMargins(32, 24, 32, 24)
        title = text_label("Wybierz pytania i rozpocznij naukę")
        title.setObjectName("title")
        layout.addWidget(title)
        form = QFormLayout()
        self.sheet_selector = QComboBox()
        form.addRow("Arkusz", self.sheet_selector)
        self.set_selector = QComboBox()
        form.addRow("Zestaw", self.set_selector)
        self.mode = QComboBox()
        self.mode.addItem("Quiz — odpowiedź po każdym pytaniu", "quiz")
        self.mode.addItem("Test — wynik po zakończeniu", "test")
        form.addRow("Rodzaj podejścia", self.mode)
        self.question_count = QComboBox()
        for count in (5, 10, 20, 50, 100):
            self.question_count.addItem(str(count), count)
        self.question_count.addItem("Wszystkie", None)
        form.addRow("Liczba pytań", self.question_count)
        self.shuffle_answers = QCheckBox("Mieszaj odpowiedzi")
        self.shuffle_answers.setToolTip(
            "Mieszaj odpowiedzi w kolejnych quizach i testach. "
            "Ustawienie jest zapamiętywane dla arkusza."
        )
        layout.addLayout(form)
        self.pool_description = text_label()
        layout.addWidget(self.pool_description)
        self.start_button = QPushButton("Rozpocznij")
        self.start_button.clicked.connect(self.start_quiz)
        layout.addWidget(self.start_button)
        self.resume_button = QPushButton()
        self.resume_button.clicked.connect(self.show_session)
        layout.addWidget(self.resume_button)
        layout.addStretch()
        self.pages.addWidget(self.home_page)

    def build_quiz(self):
        self.quiz_page = QuizPage()
        self.quiz_page.answer_selected.connect(self.select_answer)
        self.quiz_page.submit_requested.connect(self.submit_answer)
        self.quiz_page.next_requested.connect(self.next_question)
        self.quiz_page.stop_requested.connect(self.stop_quiz)
        self.quiz_page.difficulty_requested.connect(self.toggle_difficult_question)
        self.pages.addWidget(self.quiz_page)

    def build_result(self):
        self.result_page = QWidget()
        layout = QVBoxLayout(self.result_page)
        self.result_text = text_label()
        self.result_text.setObjectName("title")
        layout.addWidget(self.result_text)
        self.result_details = QPlainTextEdit()
        self.result_details.setReadOnly(True)
        layout.addWidget(self.result_details)
        button = QPushButton("Wróć do wyboru pytań")
        button.clicked.connect(self.go_home)
        layout.addWidget(button)
        self.pages.addWidget(self.result_page)

    def build_status_bar(self):
        self.status_text = QLabel()
        self.statusBar().addWidget(self.status_text, 1)
        self.statusBar().addPermanentWidget(self.shuffle_answers)
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
        self.reset_statistics_button.clicked.connect(self.reset_sheet_statistics)
        self.reset_pool_button.clicked.connect(self.reset_sheet_pool)
        for button in (self.reset_statistics_button, self.reset_pool_button):
            button.setStyleSheet("padding: 4px 10px;")
            self.statusBar().addPermanentWidget(button)

    def reload_sheets(self, sheet_id=None):
        self.sheet_selector.blockSignals(True)
        self.sheet_selector.clear()
        for identifier, name in self.catalog.sheets():
            self.sheet_selector.addItem(name, identifier)
        index = self.sheet_selector.findData(sheet_id)
        self.sheet_selector.setCurrentIndex(index if index >= 0 else 0)
        self.sheet_selector.setEnabled(self.sheet_selector.count() > 0)
        self.sheet_selector.blockSignals(False)
        self.load_sheet()

    def load_sheet(self):
        self.sheet_id = self.sheet_selector.currentData()
        settings = (
            load_settings(self.database, self.sheet_id)
            if self.sheet_id is not None
            else Settings()
        )
        controls = (self.mode, self.question_count, self.shuffle_answers)
        for control in controls:
            control.blockSignals(True)
            control.setEnabled(self.sheet_id is not None)
        self.mode.setCurrentIndex(self.mode.findData(settings.mode))
        self.question_count.setCurrentIndex(
            self.question_count.findData(settings.question_count)
        )
        self.shuffle_answers.setChecked(settings.shuffle_answers)
        for control in controls:
            control.blockSignals(False)
        self.session = load_session(self.database, self.sheet_id)
        self.reload_sets(settings.set_id)

    def reload_sets(self, set_id=None):
        self.set_selector.blockSignals(True)
        self.set_selector.clear()
        for identifier, name in self.catalog.sets(self.sheet_selector.currentData()):
            self.set_selector.addItem(name, identifier)
        index = self.set_selector.findData(set_id)
        self.set_selector.setCurrentIndex(index if index >= 0 else 0)
        self.set_selector.setEnabled(self.sheet_selector.currentData() is not None)
        self.set_selector.blockSignals(False)
        self.refresh_home()

    def sheet_changed(self):
        if not self.save_current():
            self.sheet_selector.blockSignals(True)
            self.sheet_selector.setCurrentIndex(
                self.sheet_selector.findData(self.sheet_id)
            )
            self.sheet_selector.blockSignals(False)
            return
        self.load_sheet()
        self.save_preferences()

    def refresh_home(self):
        set_id = self.set_selector.currentData()
        self.question_pool = self.catalog.questions(self.sheet_id, set_id)
        self.available_questions = unseen_questions(
            self.database, self.sheet_id, set_id, self.question_pool
        )
        kind = (
            self.catalog.get_set(self.sheet_id, set_id)["kind"]
            if set_id is not None
            else "all"
        )
        next_count = len(self.available_questions or self.question_pool)
        if self.question_pool:
            description = f"Pytania w zestawie: {len(self.question_pool)}. "
            description += (
                f"Pozostało w cyklu: {len(self.available_questions)}."
                if self.available_questions
                else "Cykl ukończony — następne podejście rozpocznie nowy."
            )
        elif kind in ("problems", "problems_keep"):
            description = "Lista jest pusta — rozwiąż najpierw inny quiz."
        elif kind == "difficult":
            description = "Lista jest pusta — oznacz pytania w quizie lub statystykach."
        elif kind == "high_error_rate":
            description = "Brak pytań spełniających wybrany próg."
        else:
            description = (
                "Brak pytań. Otwórz „Pytania i zestawy…” i zaimportuj plik JSON."
            )
        if kind == "problems":
            description += " Poprawna odpowiedź usuwa pytanie z listy problematycznych."
        elif kind == "problems_keep":
            description += " Poprawna odpowiedź zachowuje pytanie na liście."
        elif kind == "high_error_rate":
            description += (
                f" Minimum błędów: {ERROR_RATE_THRESHOLD_PERCENT}%. "
                "Źródło: historia odpowiedzi arkusza. "
                "Pytania bez odpowiedzi są pomijane."
            )
        self.pool_description.setText(description)
        self.question_count.setItemText(
            self.question_count.count() - 1, f"Wszystkie pozostałe ({next_count})"
        )
        self.start_button.setEnabled(bool(self.question_pool))
        self.statistics_action.setEnabled(self.sheet_id is not None)
        self.reset_statistics_button.setEnabled(self.sheet_id is not None)
        self.reset_pool_button.setEnabled(self.sheet_id is not None)
        self.status_text.setText(
            f"Pytań w zestawie: {len(self.question_pool)} · Pozostało: {next_count}"
            if self.sheet_id is not None
            else "Zaimportuj arkusz pytań."
        )
        self.resume_button.setEnabled(self.session is not None)
        caption = (
            "Pokaż ostatni wynik"
            if self.session and self.session.completed
            else "Wznów zapisane podejście"
        )
        self.resume_button.setText(caption)
        if self.study_window is not None:
            self.study_window.refresh_difficulty()

    def save_preferences(self):
        set_id = self.set_selector.currentData()
        settings = Settings(
            question_count=self.question_count.currentData(),
            shuffle_answers=self.shuffle_answers.isChecked(),
            mode=self.mode.currentData(),
            sheet_id=self.sheet_selector.currentData(),
            set_id=set_id,
        )
        try:
            save_settings(self.database, settings)
            return True
        except (OSError, ValueError, sqlite3.Error) as error:
            self.statusBar().showMessage(f"Nie udało się zapisać ustawień: {error}")
            return False

    def preferences_changed(self):
        if self.save_preferences():
            self.refresh_home()

    def persist(self, session, *, restart_pool=False):
        try:
            save_session(self.database, session, restart_pool=restart_pool)
            self.statusBar().clearMessage()
            return True
        except (OSError, ValueError, sqlite3.Error) as error:
            self.statusBar().showMessage(
                f"Nie udało się zapisać podejścia: {error}. Ponów operację."
            )
            return False

    def save_current(self):
        if self.session is None:
            return True
        self.session.pause()
        return self.persist(self.session)

    def resume_timer(self):
        if self.session and self.pages.currentWidget() == self.quiz_page:
            self.session.resume()

    def autosave(self):
        self.save_current()
        self.resume_timer()

    def go_home(self):
        if not self.save_current():
            self.resume_timer()
            return False
        self.pages.setCurrentWidget(self.home_page)
        self.refresh_home()
        return True

    def manage_questions(self):
        if not self.go_home():
            return
        dialog = QuestionManager(
            self.catalog,
            self.sheet_selector.currentData(),
            self.set_selector.currentData(),
            self,
        )
        self.autosave_timer.stop()
        try:
            dialog.exec()
            self.reload_sheets(dialog.sheet_selector.currentData())
            self.save_preferences()
        finally:
            self.autosave_timer.start()

    def show_study(self):
        if self.study_window is None:
            self.study_window = StudyWindow(
                self.catalog,
                self.sheet_selector.currentData(),
                self.set_selector.currentData(),
                self,
            )
        elif not self.study_window.isVisible():
            self.study_window.open_material()
        self.study_window.show()
        self.study_window.raise_()
        self.study_window.activateWindow()

    def show_statistics(self):
        if self.sheet_id is None or not self.go_home():
            return
        set_id = self.set_selector.currentData()
        StatisticsPanel(
            self.database, self.catalog, self.sheet_selector.currentData(), set_id, self
        ).exec()
        self.refresh_home()

    def start_quiz(self):
        self.refresh_home()
        if not self.question_pool:
            return
        if self.session and not self.session.completed:
            answer = QMessageBox.question(
                self,
                "Nowe podejście",
                "Zakończyć bieżące podejście tego arkusza i rozpocząć nowe?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        set_id = self.set_selector.currentData()
        if not self.save_preferences():
            return
        candidate = QuizSession.create(
            self.sheet_id,
            set_id,
            self.sheet_selector.currentText() + f" — {self.set_selector.currentText()}",
            self.available_questions or self.question_pool,
            self.question_count.currentData(),
            self.shuffle_answers.isChecked(),
            self.mode.currentData(),
        )
        if self.persist(candidate, restart_pool=not self.available_questions):
            self.session = candidate
            self.show_session()

    def select_answer(self, index):
        if self.session is None or self.session.current.confirmed:
            return
        self.session.select(index)
        self.quiz_page.highlight_selection(index)

    def submit_answer(self):
        if (
            not self.session
            or self.session.current.confirmed
            or self.session.current.selected_index is None
        ):
            return
        candidate = deepcopy(self.session)
        candidate.submit()
        if candidate.mode == "test" and not candidate.completed:
            candidate.advance()
        if self.persist(candidate):
            self.session = candidate
            self.refresh_home()
            if candidate.mode == "quiz":
                self.show_question()
            else:
                self.show_session()

    def next_question(self):
        if self.session.completed:
            self.show_result()
            return
        candidate = deepcopy(self.session)
        candidate.advance()
        if self.persist(candidate):
            self.session = candidate
            self.show_session()

    def show_session(self):
        if self.session is None:
            return
        if self.session.completed:
            self.show_result()
            return
        self.show_question()

    def show_question(self):
        self.pages.setCurrentWidget(self.quiz_page)
        flags = self.catalog.flags(self.session.sheet_id)
        difficult = bool(
            flags[self.session.current.question.question_id]["is_difficult"]
        )
        self.quiz_page.show_question(self.session, difficult)
        self.session.resume()

    def update_difficult_button(self):
        flags = self.catalog.flags(self.session.sheet_id)
        difficult = bool(
            flags[self.session.current.question.question_id]["is_difficult"]
        )
        self.quiz_page.set_difficult(difficult)

    def toggle_difficult_question(self):
        if self.session is None:
            return
        try:
            self.catalog.toggle_difficult(
                self.session.sheet_id, self.session.current.question.question_id
            )
        except (OSError, ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "Nie można zmienić oznaczenia", str(error))
        self.update_difficult_button()
        self.refresh_home()

    def reset_sheet_statistics(self):
        self.reset_sheet_data("statystyki", reset_statistics)

    def reset_sheet_pool(self):
        self.reset_sheet_data("pulę pytań", reset_question_pool)

    def reset_sheet_data(self, name, action):
        if self.sheet_id is None:
            return
        if (
            QMessageBox.question(
                self,
                "Reset",
                f"Zresetować {name} arkusza „{self.sheet_selector.currentText()}”?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            action(self.database, self.sheet_id)
        except (OSError, ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "Nie można wykonać resetu", str(error))
            return
        self.refresh_home()
        self.statusBar().showMessage(f"Zresetowano {name} wybranego arkusza.", 5000)

    def show_result(self):
        total, correct = len(self.session.items), self.session.correct
        minutes, seconds = divmod(int(self.session.elapsed_seconds), 60)
        self.result_text.setText(
            f"Wynik: {correct} / {total} ({correct / total * 100:.1f}%)\n"
            f"Czas: {minutes}:{seconds:02d}"
        )
        details = []
        for position, item in enumerate(self.session.items, 1):
            question = item.question
            selected = question.answers[item.selected_index]
            correct_answer = next(
                answer for answer in question.answers if answer.is_correct
            )
            details.append(
                f"{position}. {question.text}\n"
                f"Twoja odpowiedź: {selected.label.upper()}. {selected.text}\n"
                f"Prawidłowa: {correct_answer.label.upper()}. {correct_answer.text}\n"
                f"{question.explanation}\n{question.legal_basis}"
            )
        self.result_details.setPlainText("\n\n".join(details))
        self.pages.setCurrentWidget(self.result_page)
        self.refresh_home()

    def stop_quiz(self):
        if (
            QMessageBox.question(
                self,
                "Zakończ podejście",
                "Zakończyć podejście? Zatwierdzone odpowiedzi "
                "pozostaną w statystykach.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        if not self.save_current():
            self.resume_timer()
            return
        try:
            cancel_session(self.database, self.session.session_id)
        except sqlite3.Error as error:
            self.statusBar().showMessage(f"Nie udało się zakończyć podejścia: {error}")
            self.resume_timer()
            return
        self.session = None
        self.go_home()

    def closeEvent(self, event):
        if not self.save_preferences() or not self.save_current():
            self.resume_timer()
            event.ignore()
            return
        self.autosave_timer.stop()
        if self.study_window is not None:
            self.study_window.close()
        super().closeEvent(event)
