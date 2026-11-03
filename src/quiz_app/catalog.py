"""Arkusze i ich zestawy. Pytania zestawu muszą pochodzić z jego arkusza."""

from .database import Database
from .models import DEFAULT_SETS, ERROR_RATE_THRESHOLD_PERCENT, Answer, ImportPreview, Question


HIGH_ERROR_RATE_FILTER = (
    " AND q.id IN (SELECT h.question_id FROM answer_history h "
    "WHERE h.sheet_id = q.sheet_id GROUP BY h.question_id "
    f"HAVING SUM(1 - h.is_correct) * 100 >= COUNT(*) * {ERROR_RATE_THRESHOLD_PERCENT})"
)


def write_set(connection, sheet_id: int, name: str, question_ids: list[int]) -> int:
    name = name.strip()
    if not name or not question_ids:
        raise ValueError("Podaj nazwę zestawu i wybierz pytania.")
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("Pytanie może wystąpić w zestawie tylko raz.")
    for question_id in question_ids:
        if not connection.execute(
            "SELECT 1 FROM questions WHERE id = ? AND sheet_id = ?",
            (question_id, sheet_id),
        ).fetchone():
            raise ValueError("Pytanie nie istnieje albo należy do innego arkusza.")
    set_id = connection.execute(
        "INSERT INTO question_sets(sheet_id, name) VALUES (?, ?)", (sheet_id, name)
    ).lastrowid
    connection.executemany(
        "INSERT INTO set_questions VALUES (?, ?, ?, ?)",
        [
            (set_id, sheet_id, question_id, i)
            for i, question_id in enumerate(question_ids)
        ],
    )
    return set_id


class Catalog:
    def __init__(self, database: Database):
        self.database = database

    def sheets(self) -> list[tuple[int, str]]:
        with self.database.connect() as connection:
            return [
                (row["id"], row["name"])
                for row in connection.execute(
                    "SELECT id, name FROM sheets ORDER BY name, id"
                )
            ]

    def sets(self, sheet_id):
        with self.database.connect() as connection:
            return [
                (row["id"], row["name"])
                for row in connection.execute(
                    "SELECT id, CASE WHEN kind = 'high_error_rate' THEN ? "
                    "ELSE name END AS name FROM question_sets WHERE sheet_id = ? "
                    "ORDER BY CASE kind WHEN 'all' THEN 0 WHEN 'problems' THEN 1 "
                    "WHEN 'problems_keep' THEN 2 WHEN 'difficult' THEN 3 "
                    "WHEN 'high_error_rate' THEN 4 ELSE 5 END, name, id",
                    (DEFAULT_SETS["high_error_rate"], sheet_id),
                )
            ]

    def custom_sets(self, sheet_id):
        with self.database.connect() as connection:
            return [
                (row["id"], row["name"])
                for row in connection.execute(
                    "SELECT id, name FROM question_sets WHERE sheet_id = ? "
                    "AND kind = 'custom' ORDER BY name, id",
                    (sheet_id,),
                )
            ]

    def get_set(self, sheet_id, set_id):
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, sheet_id, name, kind FROM question_sets "
                "WHERE id = ? AND sheet_id = ?",
                (set_id, sheet_id),
            ).fetchone()
        if row is None:
            raise ValueError("Zestaw nie należy do wybranego arkusza.")
        result = dict(row)
        if result["kind"] == "high_error_rate":
            result["name"] = DEFAULT_SETS["high_error_rate"]
        return result

    def default_set_id(self, sheet_id, kind="all"):
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id FROM question_sets WHERE sheet_id = ? AND kind = ?",
                (sheet_id, kind),
            ).fetchone()
        return row[0] if row else None

    def questions(
        self, sheet_id: int | None, set_id: int | None = None
    ) -> list[Question]:
        if sheet_id is None:
            return []
        kind = self.get_set(sheet_id, set_id)["kind"] if set_id is not None else "all"
        with self.database.connect() as connection:
            parameters = (sheet_id,)
            sql = "SELECT q.* FROM questions q WHERE q.sheet_id = ?"
            order = " ORDER BY q.number"
            if kind == "custom":
                sql = (
                    "SELECT q.* FROM questions q "
                    "JOIN set_questions s ON s.question_id = q.id "
                    "WHERE q.sheet_id = ? AND s.set_id = ?"
                )
                parameters = (sheet_id, set_id)
                order = " ORDER BY s.position"
            if kind in ("problems", "problems_keep"):
                sql += " AND q.is_problem = 1"
            elif kind == "difficult":
                sql += " AND q.is_difficult = 1"
            elif kind == "high_error_rate":
                sql += HIGH_ERROR_RATE_FILTER
            questions = []
            for row in connection.execute(sql + order, parameters).fetchall():
                answer_rows = connection.execute(
                    "SELECT * FROM answers WHERE question_id = ? ORDER BY position",
                    (row["id"],),
                ).fetchall()
                answers = tuple(
                    Answer(answer["label"], answer["text"], bool(answer["is_correct"]))
                    for answer in answer_rows
                )
                question = Question(
                    number=row["number"],
                    text=row["text"],
                    answers=answers,
                    question_id=row["id"],
                    sheet_id=row["sheet_id"],
                    legal_basis=row["legal_basis"],
                    explanation=row["explanation"],
                )
                questions.append(question)
            return questions

    def flags(self, sheet_id):
        with self.database.connect() as connection:
            return {
                row["id"]: dict(row)
                for row in connection.execute(
                    "SELECT id, is_problem, is_difficult FROM questions "
                    "WHERE sheet_id = ?",
                    (sheet_id,),
                )
            }

    def toggle_difficult(self, sheet_id, question_id):
        with self.database.connect() as connection:
            changed = connection.execute(
                "UPDATE questions SET is_difficult = 1 - is_difficult "
                "WHERE id = ? AND sheet_id = ?",
                (question_id, sheet_id),
            ).rowcount
            if not changed:
                raise ValueError("Pytanie nie należy do wybranego arkusza.")

    def delete_sheet(self, sheet_id: int):
        with self.database.connect() as connection:
            connection.execute("DELETE FROM sheets WHERE id = ?", (sheet_id,))

    def delete_sets(self, sheet_id: int):
        with self.database.connect() as connection:
            connection.execute(
                "DELETE FROM question_sets WHERE sheet_id = ? AND kind = 'custom'",
                (sheet_id,),
            )

    def delete_explanations(self, sheet_id: int):
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE questions SET explanation = '' WHERE sheet_id = ?", (sheet_id,)
            )


def import_questions(
    database: Database, preview: ImportPreview, *, connection=None
) -> int:
    with database.connect(connection) as connection:
        existing = connection.execute(
            "SELECT id FROM sheets WHERE content_hash = ?", (preview.content_hash,)
        ).fetchone()
        if existing:
            return existing[0]
        sheet_id = connection.execute(
            "INSERT INTO sheets(name, content_hash) VALUES (?, ?)",
            (preview.name, preview.content_hash),
        ).lastrowid
        connection.executemany(
            "INSERT INTO question_sets(sheet_id, name, kind) VALUES (?, ?, ?)",
            [(sheet_id, name, kind) for kind, name in DEFAULT_SETS.items()],
        )
        default_id = connection.execute(
            "SELECT id FROM question_sets WHERE sheet_id = ? AND kind = 'all'",
            (sheet_id,),
        ).fetchone()[0]
        connection.execute(
            "UPDATE sheets SET selected_set_id = ? WHERE id = ?", (default_id, sheet_id)
        )
        for question in preview.questions:
            question_id = connection.execute(
                "INSERT INTO questions(sheet_id, number, text, "
                "legal_basis, explanation) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    sheet_id,
                    question.number,
                    question.text,
                    question.legal_basis,
                    question.explanation,
                ),
            ).lastrowid
            connection.executemany(
                "INSERT INTO answers VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        question_id,
                        position,
                        answer.label,
                        answer.text,
                        answer.is_correct,
                    )
                    for position, answer in enumerate(question.answers)
                ],
            )
        return sheet_id


def _find_identical_set(connection, sheet_id, name, question_ids):
    candidates = connection.execute(
        "SELECT id FROM question_sets WHERE sheet_id = ? AND name = ? "
        "AND kind = 'custom'",
        (sheet_id, name),
    ).fetchall()
    for candidate in candidates:
        saved_questions = connection.execute(
            "SELECT question_id FROM set_questions WHERE set_id = ? ORDER BY position",
            (candidate[0],),
        )
        if [row[0] for row in saved_questions] == question_ids:
            return candidate[0]
    return None


def import_question_sets(
    database: Database,
    sheet_id: int,
    prepared: list[tuple[str, list[int]]],
    *,
    connection=None,
) -> tuple[list[int], int]:
    set_ids = []
    skipped = 0
    with database.connect(connection) as connection:
        for name, question_ids in prepared:
            existing_id = _find_identical_set(connection, sheet_id, name, question_ids)
            if existing_id is not None:
                set_ids.append(existing_id)
                skipped += 1
                continue
            set_ids.append(write_set(connection, sheet_id, name, question_ids))
    return set_ids, skipped


def import_explanations(
    database: Database, prepared: list[tuple[int, str]], *, connection=None
):
    with database.connect(connection) as connection:
        for question_id, text in prepared:
            if not connection.execute(
                "UPDATE questions SET explanation = ? WHERE id = ?", (text, question_id)
            ).rowcount:
                raise ValueError("Pytanie zostało usunięte. Ponów import objaśnień.")
