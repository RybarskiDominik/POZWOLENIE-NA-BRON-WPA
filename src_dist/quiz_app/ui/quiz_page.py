"""Wyświetlanie pytania i odpowiedzi bez odczytu ani zapisu bazy."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


def text_label(text=""):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class AnswerRow(QWidget):
    def __init__(self, answer):
        super().__init__()
        self.setObjectName("answerRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button = QRadioButton(f"{answer.label.upper()}.")
        self.button.setAccessibleName(f"{answer.label}: {answer.text}")
        layout = QHBoxLayout(self)
        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(text_label(answer.text), 1)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.button.isEnabled():
            self.button.click()
            event.accept()
        else:
            super().mousePressEvent(event)

    def highlight(self, color=""):
        if not color:
            self.setStyleSheet("")
            return
        self.setStyleSheet(
            f"QWidget#answerRow {{ background-color: {color}; border-radius: 6px; }}"
            "QLabel, QRadioButton { color: #17202a; background: transparent; }"
        )


class QuizPage(QWidget):
    answer_selected = Signal(int)
    submit_requested = Signal()
    next_requested = Signal()
    stop_requested = Signal()
    difficulty_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.progress_text = text_label()
        self.progress = QProgressBar()
        layout.addWidget(self.progress_text)
        layout.addWidget(self.progress)
        content = QWidget()
        body = QVBoxLayout(content)
        self.question_text = text_label()
        self.question_text.setObjectName("question")
        body.addWidget(self.question_text)
        self.answers_layout = QVBoxLayout()
        self.answer_group = QButtonGroup(self)
        self.answer_group.idClicked.connect(self.answer_selected)
        body.addLayout(self.answers_layout)
        self.feedback = text_label()
        body.addWidget(self.feedback)
        body.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        buttons = QHBoxLayout()
        self.stop_button = QPushButton("Zakończ podejście")
        self.stop_button.clicked.connect(self.stop_requested)
        self.submit_button = QPushButton("Zatwierdź odpowiedź")
        self.submit_button.clicked.connect(self.submit_requested)
        self.next_button = QPushButton("Następne pytanie")
        self.next_button.clicked.connect(self.next_requested)
        self.difficult_button = QPushButton("Oznacz jako trudne")
        self.difficult_button.setCheckable(True)
        self.difficult_button.clicked.connect(self.difficulty_requested)
        for button in (
            self.stop_button,
            self.difficult_button,
            self.submit_button,
            self.next_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def show_question(self, session, difficult):
        item = session.current
        question = item.question
        self.progress_text.setText(
            f"{session.title} · Pytanie {session.position + 1} "
            f"z {len(session.items)} · numer w bazie: {question.number}"
        )
        self.progress.setRange(0, len(session.items))
        self.progress.setValue(sum(item.confirmed for item in session.items))
        self.question_text.setText(question.text)
        self.set_difficult(difficult)
        while self.answers_layout.count():
            row = self.answers_layout.takeAt(0).widget()
            self.answer_group.removeButton(row.button)
            row.hide()
            row.deleteLater()
        for index, answer in enumerate(question.answers):
            row = AnswerRow(answer)
            row.button.setEnabled(not item.confirmed)
            if item.confirmed:
                row.setCursor(Qt.CursorShape.ArrowCursor)
                if answer.is_correct:
                    row.highlight("#c8e6c9")
                elif index == item.selected_index:
                    row.highlight("#ffcdd2")
            elif index == item.selected_index:
                row.highlight("#fff3b0")
            self.answer_group.addButton(row.button, index)
            self.answers_layout.addWidget(row)
        if item.selected_index is not None:
            self.answer_group.button(item.selected_index).setChecked(True)
        self.submit_button.setVisible(not item.confirmed)
        self.submit_button.setEnabled(item.selected_index is not None)
        self.next_button.setVisible(item.confirmed)
        self.next_button.setText(
            "Zobacz podsumowanie" if session.completed else "Następne pytanie"
        )
        self.stop_button.setVisible(not session.completed)
        self.feedback.clear()
        if item.confirmed:
            correct = next(a for a in question.answers if a.is_correct)
            message = (
                "Poprawna odpowiedź." if item.is_correct else "Niepoprawna odpowiedź."
            )
            self.feedback.setText(
                f"{message}\nPrawidłowa: {correct.label.upper()}. {correct.text}\n\n"
                f"{question.explanation}\n{question.legal_basis}"
            )

    def highlight_selection(self, index):
        for position in range(self.answers_layout.count()):
            row = self.answers_layout.itemAt(position).widget()
            row.highlight("#fff3b0" if position == index else "")
        self.submit_button.setEnabled(True)

    def set_difficult(self, difficult):
        self.difficult_button.setChecked(difficult)
        self.difficult_button.setText(
            "Usuń oznaczenie „Trudne”" if difficult else "Oznacz jako trudne"
        )
