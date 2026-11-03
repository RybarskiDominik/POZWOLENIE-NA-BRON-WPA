"""Zapis i odtwarzanie ustawień, sesji oraz postępu nauki arkusza."""

import json
from dataclasses import asdict, replace

from .database import Database
from .models import Answer, Question, SessionItem, Settings
from .quiz import QuizSession


def load_settings(database: Database, sheet_id: int | None = None) -> Settings:
    with database.connect() as connection:
        if sheet_id is None:
            state = connection.execute("SELECT sheet_id FROM app_state").fetchone()
            sheet_id = state["sheet_id"]
        if sheet_id is None:
            first = connection.execute(
                "SELECT id FROM sheets ORDER BY name, id LIMIT 1"
            ).fetchone()
            sheet_id = first[0] if first else None
        row = connection.execute(
            "SELECT * FROM sheets WHERE id = ?", (sheet_id,)
        ).fetchone()
        if row is None:
            return Settings()
        set_id = row["selected_set_id"]
        if set_id is None:
            set_id = connection.execute(
                "SELECT id FROM question_sets WHERE sheet_id = ? AND kind = 'all'",
                (sheet_id,),
            ).fetchone()[0]
        return Settings(
            question_count=row["question_count"],
            shuffle_answers=bool(row["shuffle_answers"]),
            mode=row["mode"],
            sheet_id=row["id"],
            set_id=set_id,
        )


def save_settings(database: Database, settings: Settings):
    with database.connect() as connection:
        if (
            settings.set_id is not None
            and not connection.execute(
                "SELECT 1 FROM question_sets WHERE id = ? AND sheet_id = ?",
                (settings.set_id, settings.sheet_id),
            ).fetchone()
        ):
            raise ValueError("Zestaw nie należy do wybranego arkusza.")
        if settings.sheet_id is not None:
            changed = connection.execute(
                "UPDATE sheets SET question_count = ?, shuffle_answers = ?, "
                "mode = ?, selected_set_id = ? WHERE id = ?",
                (
                    settings.question_count,
                    settings.shuffle_answers,
                    settings.mode,
                    settings.set_id,
                    settings.sheet_id,
                ),
            ).rowcount
            if not changed:
                raise ValueError("Arkusz nie istnieje.")
        connection.execute(
            "UPDATE app_state SET sheet_id = ? WHERE id = 1", (settings.sheet_id,)
        )


def save_session(database: Database, session: QuizSession, *, restart_pool=False):
    """Sesja musi mieć zatrzymany zegar; zatwierdzone odpowiedzi są niezmienne."""
    with database.connect() as connection:
        existing = connection.execute(
            "SELECT s.status, s.sheet_id, s.set_id, q.kind FROM quiz_sessions s "
            "LEFT JOIN question_sets q ON q.id = s.set_id WHERE s.id = ?",
            (session.session_id,),
        ).fetchone()
        if existing and existing["status"] == "cancelled":
            raise ValueError("To podejście zostało zakończone.")
        if existing and existing["sheet_id"] != session.sheet_id:
            raise ValueError("Nie można przenieść podejścia do innego arkusza.")
        if (
            existing
            and existing["set_id"] is not None
            and existing["set_id"] != session.set_id
        ):
            raise ValueError("Nie można zmienić zestawu rozpoczętego podejścia.")
        if existing is None:
            selected = connection.execute(
                "SELECT kind FROM question_sets WHERE id = ? AND sheet_id = ?",
                (session.set_id, session.sheet_id),
            ).fetchone()
            if selected is None:
                raise ValueError("Zestaw nie należy do wybranego arkusza.")
            connection.execute(
                "UPDATE quiz_sessions SET status = 'cancelled', "
                "finished_at = CURRENT_TIMESTAMP "
                "WHERE sheet_id = ? AND status = 'active'",
                (session.sheet_id,),
            )
            if restart_pool:
                connection.execute(
                    "DELETE FROM question_progress WHERE set_id = ?", (session.set_id,)
                )
        set_id = existing["set_id"] if existing else session.set_id
        kind = existing["kind"] if existing else selected["kind"]
        status = "completed" if session.completed else "active"
        connection.execute(
            "INSERT INTO quiz_sessions(id, sheet_id, set_id, title, mode, "
            "status, position, "
            "elapsed_seconds, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "CASE WHEN ? THEN CURRENT_TIMESTAMP END) "
            "ON CONFLICT(id) DO UPDATE SET status = excluded.status, "
            "position = excluded.position, "
            "elapsed_seconds = excluded.elapsed_seconds, "
            "finished_at = COALESCE(quiz_sessions.finished_at, excluded.finished_at)",
            (
                session.session_id,
                session.sheet_id,
                set_id,
                session.title,
                session.mode,
                status,
                session.position,
                session.elapsed_seconds,
                session.started_at,
                session.completed,
            ),
        )
        _save_session_items(connection, session, existing, set_id, kind)
        connection.execute(
            "UPDATE sheets SET last_session_id = ? WHERE id = ?",
            (session.session_id, session.sheet_id),
        )


def _save_session_items(connection, session, existing, set_id, kind):
    """Zapisz pytania sesji; zatwierdzone odpowiedzi tylko sprawdź."""
    for position, item in enumerate(session.items):
        if (
            existing is None
            and not connection.execute(
                "SELECT 1 FROM questions WHERE id = ? AND sheet_id = ?",
                (item.question.question_id, session.sheet_id),
            ).fetchone()
        ):
            raise ValueError("Pytanie nie należy do arkusza tego podejścia.")
        previous = connection.execute(
            "SELECT question_id, confirmed, selected_index FROM session_items "
            "WHERE session_id = ? AND position = ?",
            (session.session_id, position),
        ).fetchone()
        if previous and previous["confirmed"]:
            if not item.confirmed or previous["selected_index"] != item.selected_index:
                raise ValueError("Nie można zmienić zatwierdzonej odpowiedzi.")
            continue
        question_id = previous["question_id"] if previous else item.question.question_id
        connection.execute(
            "INSERT INTO session_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id, position) DO UPDATE SET "
            "selected_index = excluded.selected_index, "
            "confirmed = excluded.confirmed, is_correct = excluded.is_correct, "
            "elapsed_seconds = excluded.elapsed_seconds, "
            "answered_at = excluded.answered_at",
            (
                session.session_id,
                position,
                question_id,
                json.dumps(asdict(item.question), ensure_ascii=False),
                item.selected_index,
                item.confirmed,
                item.is_correct,
                item.elapsed_seconds,
                item.answered_at,
            ),
        )
        if item.confirmed:
            record_answer(connection, session, position, item, set_id, kind)


def record_answer(connection, session, position, item, set_id, kind):
    """Zapisz skutki nowej odpowiedzi raz, w transakcji zapisu sesji."""
    question_id = item.question.question_id
    connection.execute(
        "INSERT INTO answer_history(sheet_id, session_id, position, question_id, "
        "is_correct, elapsed_seconds, answered_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            session.sheet_id,
            session.session_id,
            position,
            question_id,
            item.is_correct,
            item.elapsed_seconds,
            item.answered_at,
        ),
    )
    if not item.is_correct or kind != "problems_keep":
        connection.execute(
            "UPDATE questions SET is_problem = ? WHERE id = ? AND sheet_id = ?",
            (not item.is_correct, question_id, session.sheet_id),
        )
    if set_id is None:
        return
    connection.execute(
        "INSERT OR IGNORE INTO question_progress "
        "(sheet_id, set_id, question_id) VALUES (?, ?, ?)",
        (session.sheet_id, set_id, question_id),
    )


def load_session(database: Database, sheet_id: int | None) -> QuizSession | None:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT s.* FROM quiz_sessions s JOIN sheets p ON p.last_session_id = s.id "
            "AND p.id = s.sheet_id "
            "WHERE s.sheet_id = ? AND s.status != 'cancelled'",
            (sheet_id,),
        ).fetchone()
        if row is None:
            return None
        items = []
        for item in connection.execute(
            "SELECT * FROM session_items WHERE session_id = ? ORDER BY position",
            (row["id"],),
        ):
            data = json.loads(item["question_json"])
            data["answers"] = tuple(Answer(**answer) for answer in data["answers"])
            question = replace(Question(**data), question_id=item["question_id"])
            selected = item["selected_index"]
            if selected is not None and not 0 <= selected < len(question.answers):
                raise ValueError("Zapisana odpowiedź ma nieprawidłowy indeks.")
            items.append(
                SessionItem(
                    question=question,
                    selected_index=selected,
                    confirmed=bool(item["confirmed"]),
                    elapsed_seconds=item["elapsed_seconds"],
                    answered_at=item["answered_at"],
                )
            )
        if not items or not 0 <= row["position"] < len(items):
            raise ValueError("Zapisana sesja nie zawiera prawidłowej pozycji pytania.")
        return QuizSession(
            sheet_id=row["sheet_id"],
            set_id=row["set_id"],
            title=row["title"],
            mode=row["mode"],
            items=items,
            session_id=row["id"],
            position=row["position"],
            elapsed_seconds=row["elapsed_seconds"],
            started_at=row["started_at"],
        )


def cancel_session(database: Database, session_id: str):
    with database.connect() as connection:
        connection.execute(
            "UPDATE quiz_sessions SET status = 'cancelled', "
            "finished_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'active'",
            (session_id,),
        )
        connection.execute(
            "UPDATE sheets SET last_session_id = NULL WHERE last_session_id = ?",
            (session_id,),
        )


def unseen_questions(database, sheet_id, set_id, questions):
    with database.connect() as connection:
        seen = {
            row[0]
            for row in connection.execute(
                "SELECT question_id FROM question_progress "
                "WHERE sheet_id = ? AND set_id = ?",
                (sheet_id, set_id),
            )
        }
    return [question for question in questions if question.question_id not in seen]


def reset_question_pool(database, sheet_id):
    with database.connect() as connection:
        connection.execute(
            "DELETE FROM question_progress WHERE sheet_id = ?", (sheet_id,)
        )


def reset_statistics(database: Database, sheet_id: int):
    with database.connect() as connection:
        connection.execute("DELETE FROM answer_history WHERE sheet_id = ?", (sheet_id,))
