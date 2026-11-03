"""Jednorazowy import dołączonego arkusza przy starcie aplikacji z pustą bazą."""

from dataclasses import replace

from .catalog import import_explanations, import_question_sets, import_questions
from .importers import prepare_explanations, prepare_question_sets, preview_import
from .paths import QUESTIONS_DIRECTORY

# False pomija wybrany plik podczas pierwszego importu do pustej bazy.
IMPORT_QUESTION_SETS = False
IMPORT_LEGAL_BASIS = True

QUESTIONS_PATH = QUESTIONS_DIRECTORY / "egzamin_na_broń_WPA_200.json"
QUESTION_SETS_PATH = QUESTIONS_DIRECTORY / "egzamin_na_broń_WPA_200_zestawy_pytań.json"
LEGAL_BASIS_PATH = QUESTIONS_DIRECTORY / "egzamin_na_broń_WPA_200_podstawy_prawne.json"


def import_on_first_start(database):
    """Zaimportuj wybrane pliki razem; błąd wycofuje również znacznik importu."""
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        state = connection.execute(
            "SELECT initial_import_done FROM app_state WHERE id = 1"
        ).fetchone()
        if state["initial_import_done"]:
            return None
        existing_sheet = connection.execute("SELECT 1 FROM sheets LIMIT 1").fetchone()
        if existing_sheet:
            connection.execute(
                "UPDATE app_state SET initial_import_done = 1 WHERE id = 1"
            )
            return None

        preview = preview_import(QUESTIONS_PATH)
        sheet_id = import_questions(database, preview, connection=connection)
        question_ids = dict(
            connection.execute(
                "SELECT number, id FROM questions WHERE sheet_id = ?", (sheet_id,)
            )
        )
        questions = [
            replace(
                question, question_id=question_ids[question.number], sheet_id=sheet_id
            )
            for question in preview.questions
        ]
        if IMPORT_QUESTION_SETS:
            question_sets = prepare_question_sets(QUESTION_SETS_PATH, questions)
            import_question_sets(
                database, sheet_id, question_sets, connection=connection
            )
        if IMPORT_LEGAL_BASIS:
            explanations = prepare_explanations(LEGAL_BASIS_PATH, questions)
            import_explanations(database, explanations, connection=connection)
        connection.execute(
            "UPDATE app_state SET initial_import_done = 1, sheet_id = ? WHERE id = 1",
            (sheet_id,),
        )
        return sheet_id
