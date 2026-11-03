"""Statystyki odpowiedzi niezależne od bieżącej sesji i pamięci cyklu."""

from .catalog import HIGH_ERROR_RATE_FILTER, Catalog
from .database import Database


def recent_average(seconds) -> float | None:
    """Weź do pięciu ostatnich czasów i odrzuć jeden najdłuższy."""
    recent = list(seconds)[:5]
    if not recent:
        return None
    if len(recent) > 1:
        recent.remove(max(recent))
    return sum(recent) / len(recent)


def load_statistics(
    database: Database, sheet_id: int | None, set_id: int | None = None
) -> dict:
    parameters = [sheet_id]
    condition = " WHERE a.sheet_id = ?"
    kind = (
        Catalog(database).get_set(sheet_id, set_id)["kind"]
        if set_id is not None
        else "all"
    )
    if kind == "custom":
        condition += " AND s.set_id = ?"
        parameters.append(set_id)
    if kind in ("problems", "problems_keep"):
        condition += " AND q.is_problem = 1"
    elif kind == "difficult":
        condition += " AND q.is_difficult = 1"
    elif kind == "high_error_rate":
        condition += HIGH_ERROR_RATE_FILTER
    source = (
        " FROM answer_history a JOIN quiz_sessions s ON s.id = a.session_id "
        "JOIN questions q ON q.id = a.question_id" + condition
    )
    with database.connect() as connection:
        answers = connection.execute(
            "SELECT a.*" + source + " ORDER BY a.id DESC", parameters
        ).fetchall()
        history = connection.execute(
            "SELECT s.started_at, s.title, s.mode, s.status, s.elapsed_seconds, "
            "(SELECT COUNT(*) FROM session_items WHERE session_id = s.id) AS total, "
            "COUNT(*) AS answered, SUM(a.is_correct) AS correct"
            + source
            + " GROUP BY s.id ORDER BY s.started_at DESC",
            parameters,
        ).fetchall()
        current = connection.execute(
            "SELECT s.title, s.status, COUNT(*) AS total, "
            "SUM(i.confirmed) AS answered, "
            "COALESCE(SUM(i.is_correct), 0) AS correct FROM quiz_sessions s "
            "JOIN sheets p ON p.last_session_id = s.id AND p.id = s.sheet_id "
            "JOIN session_items i ON i.session_id = s.id WHERE s.sheet_id = ? "
            "GROUP BY s.id",
            (sheet_id,),
        ).fetchone()
        flags = connection.execute(
            "SELECT COALESCE(SUM(is_problem), 0) AS problems, "
            "COALESCE(SUM(is_difficult), 0) AS difficult "
            "FROM questions WHERE sheet_id = ?",
            (sheet_id,),
        ).fetchone()
    question_statistics = {}
    response_times = {}
    daily_activity = {}
    for answer in answers:
        question_id = answer["question_id"]
        counts = question_statistics.setdefault(
            question_id, {"attempts": 0, "correct": 0}
        )
        counts["attempts"] += 1
        counts["correct"] += answer["is_correct"]
        response_times.setdefault(question_id, []).append(answer["elapsed_seconds"])
        day = answer["answered_at"][:10]
        activity = daily_activity.setdefault(
            day, {"day": day, "attempts": 0, "correct": 0}
        )
        activity["attempts"] += 1
        activity["correct"] += answer["is_correct"]
    for question_id, counts in question_statistics.items():
        counts["errors"] = counts["attempts"] - counts["correct"]
        counts["average_seconds"] = recent_average(response_times[question_id])
    correct = sum(answer["is_correct"] for answer in answers)
    return {
        "attempts": len(answers),
        "correct": correct,
        "errors": len(answers) - correct,
        "average_seconds": recent_average(a["elapsed_seconds"] for a in answers),
        "questions": question_statistics,
        "days": [
            daily_activity[day] for day in sorted(daily_activity, reverse=True)[:14]
        ],
        "history": [dict(row) for row in history],
        "current": dict(current) if current else None,
        "problems": flags["problems"],
        "difficult": flags["difficult"],
    }
