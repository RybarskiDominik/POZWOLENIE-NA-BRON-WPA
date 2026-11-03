"""Wspólne kolory listy oraz podgląd pytania, odpowiedzi i objaśnień."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QTextCharFormat


def highlight_difficult_questions(questions, flags):
    for index in range(questions.count()):
        item = questions.item(index)
        question = item.data(Qt.ItemDataRole.UserRole)
        difficult = flags.get(question.question_id, {}).get("is_difficult", False)
        item.setForeground(QColor("#8e24aa") if difficult else QBrush())


def show_question_details(details, question, *, include_explanation=False):
    details.clear()
    if question is None:
        return
    cursor = details.textCursor()
    cursor.insertText(question.text, QTextCharFormat())
    if question.legal_basis:
        separator = " " if question.text.endswith(":") else ": "
        cursor.insertText(f"{separator}{question.legal_basis}")
    for answer in question.answers:
        answer_format = QTextCharFormat()
        if answer.is_correct:
            answer_format.setForeground(Qt.GlobalColor.darkGreen)
        cursor.insertText(f"\n{answer.label.upper()}. {answer.text}", answer_format)
    if include_explanation and question.explanation:
        cursor.insertText(f"\n\n{question.explanation}", QTextCharFormat())
