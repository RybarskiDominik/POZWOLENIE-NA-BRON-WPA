"""Losowanie pytań, odpowiedzi, ocenianie i zegar quizu."""

import random
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4

from .models import Question, SessionItem


def arrange_answers(question: Question, order: list[int]) -> Question:
    """Zachowaj znaczenie odwołań typu „a. i b.” przy mieszaniu odpowiedzi."""
    labels = [answer.label for answer in question.answers]
    label_mapping = {
        question.answers[original_position].label: labels[new_position]
        for new_position, original_position in enumerate(order)
    }
    answers = []
    for new_position, original_position in enumerate(order):
        answer = question.answers[original_position]
        text = re.sub(
            r"\b([a-z])\.",
            lambda match: label_mapping.get(match.group(1), match.group(1)) + ".",
            answer.text,
        )
        answers.append(replace(answer, label=labels[new_position], text=text))
    return replace(question, answers=tuple(answers))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class QuizSession:
    sheet_id: int
    set_id: int | None
    title: str
    mode: str
    items: list[SessionItem]
    session_id: str = field(default_factory=lambda: str(uuid4()))
    position: int = 0
    elapsed_seconds: float = 0.0
    started_at: str = field(default_factory=now)
    _timer_started_at: float | None = field(default=None, repr=False, compare=False)

    @classmethod
    def create(cls, sheet_id, set_id, title, questions, count, shuffle_answers, mode):
        if mode not in ("quiz", "test"):
            raise ValueError("Wybierz quiz albo test.")
        if not questions:
            raise ValueError("Wybrany arkusz lub zestaw nie zawiera pytań.")
        if any(question.sheet_id != sheet_id for question in questions):
            raise ValueError("Pytania muszą należeć do wybranego arkusza.")
        count = len(questions) if count is None else min(count, len(questions))
        if count < 1:
            raise ValueError("Wybierz co najmniej jedno pytanie.")
        items = []
        for question in random.sample(questions, count):
            order = list(range(len(question.answers)))
            if shuffle_answers:
                random.shuffle(order)
            items.append(SessionItem(arrange_answers(question, order)))
        return cls(
            sheet_id=sheet_id, set_id=set_id, title=title, mode=mode, items=items
        )

    @property
    def current(self) -> SessionItem:
        return self.items[self.position]

    @property
    def completed(self) -> bool:
        return all(item.confirmed for item in self.items)

    @property
    def correct(self) -> int:
        return sum(item.is_correct is True for item in self.items)

    def select(self, index: int):
        if self.current.confirmed:
            raise ValueError("Odpowiedź jest już zatwierdzona.")
        answer_count = len(self.current.question.answers)
        if type(index) is not int or not 0 <= index < answer_count:
            raise ValueError("Wybierz jedną z dostępnych odpowiedzi.")
        self.current.selected_index = index

    def submit(self):
        if self.current.confirmed or self.current.selected_index is None:
            raise ValueError("Wybierz nową odpowiedź przed zatwierdzeniem.")
        self.pause()
        self.current.confirmed = True
        self.current.answered_at = now()

    def advance(self):
        if not self.current.confirmed or self.position + 1 >= len(self.items):
            raise ValueError("Nie można przejść do następnego pytania.")
        self.position += 1

    def resume(self):
        if (
            not self.completed
            and not self.current.confirmed
            and self._timer_started_at is None
        ):
            self._timer_started_at = monotonic()

    def pause(self):
        if self._timer_started_at is not None:
            seconds = monotonic() - self._timer_started_at
            self.elapsed_seconds += seconds
            self.current.elapsed_seconds += seconds
            self._timer_started_at = None
