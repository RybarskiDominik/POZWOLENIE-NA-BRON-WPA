"""Modele danych niezależne od SQLite i interfejsu."""

from dataclasses import dataclass

# Minimalny odsetek błędnych odpowiedzi (0–100). Po zmianie uruchom aplikację ponownie.
ERROR_RATE_THRESHOLD_PERCENT = 10


@dataclass(frozen=True)
class Answer:
    label: str
    text: str
    is_correct: bool


@dataclass(frozen=True)
class Question:
    number: int
    text: str
    answers: tuple[Answer, ...]
    question_id: int = 0
    sheet_id: int = 0
    legal_basis: str = ""
    explanation: str = ""


@dataclass
class Settings:
    question_count: int | None = 20
    shuffle_answers: bool = True
    mode: str = "quiz"
    sheet_id: int | None = None
    set_id: int | None = None


@dataclass
class SessionItem:
    question: Question
    selected_index: int | None = None
    confirmed: bool = False
    elapsed_seconds: float = 0.0
    answered_at: str | None = None

    @property
    def is_correct(self) -> bool | None:
        if not self.confirmed:
            return None
        return self.question.answers[self.selected_index].is_correct


@dataclass
class ImportPreview:
    name: str
    questions: list[Question]
    content_hash: str


DEFAULT_SETS = {
    "all": "Wszystkie pytania",
    "problems": "Moje problematyczne pytania",
    "problems_keep": "Moje problematyczne pytania (nieusuwanie poprawnych z bazy)",
    "difficult": "Oznaczone jako trudne",
    "high_error_rate": f"Błędne odpowiedzi (min. {ERROR_RATE_THRESHOLD_PERCENT}%)",
}
