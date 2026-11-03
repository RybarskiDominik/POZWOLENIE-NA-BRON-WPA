"""Odczyt i walidacja plików JSON przed zapisem do bazy."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .models import Answer, ImportPreview, Question


def _parse_answers(raw_answers) -> list[Answer]:
    if not isinstance(raw_answers, list) or len(raw_answers) < 2:
        raise ValueError("Potrzebne są co najmniej dwie odpowiedzi.")
    answers = []
    for answer in raw_answers:
        label = answer["label_id"]
        content = answer["text"]
        correct = answer["is_correct"]
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Brak etykiety odpowiedzi.")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Brak treści odpowiedzi.")
        if type(correct) is not bool:
            raise ValueError("is_correct musi mieć wartość true albo false.")
        answers.append(Answer(label.strip(), content.strip(), correct))
    if len({a.label for a in answers}) != len(answers):
        raise ValueError("Etykiety odpowiedzi muszą być unikalne.")
    if sum(a.is_correct for a in answers) != 1:
        raise ValueError("Wskaż dokładnie jedną poprawną odpowiedź.")
    return answers


def parse_questions(document: dict) -> list[Question]:
    if not isinstance(document, dict) or not isinstance(
        document.get("questions"), list
    ):
        raise ValueError("Dokument musi zawierać listę questions.")
    if not document["questions"]:
        raise ValueError("Arkusz nie zawiera pytań.")
    questions = []
    seen_numbers = set()
    for position, item in enumerate(document["questions"], 1):
        try:
            number = item["number"]
            text = item["question"]
            if type(number) is not int or number < 1 or number in seen_numbers:
                raise ValueError("Numer musi być dodatni i unikalny w arkuszu.")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Brak treści pytania.")
            answers = _parse_answers(item["answers"])
            legal_basis = item.get("legal_basis", "")
            if not isinstance(legal_basis, str):
                raise ValueError("legal_basis musi być tekstem.")
            explanation = item.get("explanation", "")
            if not isinstance(explanation, str):
                raise ValueError("explanation musi być tekstem.")
            questions.append(
                Question(
                    number,
                    text.strip(),
                    tuple(answers),
                    legal_basis=legal_basis,
                    explanation=explanation,
                )
            )
            seen_numbers.add(number)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Pytanie {position}: {error}") from error
    return questions


def preview_import(path: Path) -> ImportPreview:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    questions = parse_questions(document)
    name = document.get("questions_title", path.stem)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Podaj nazwę arkusza w questions_title.")
    name = name.strip()
    content = json.dumps(
        {
            "name": name,
            "questions": [
                asdict(question)
                for question in sorted(questions, key=lambda question: question.number)
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return ImportPreview(name, questions, content_hash)


def prepare_question_sets(
    path: Path, questions: list[Question]
) -> list[tuple[str, list[int]]]:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict) or not isinstance(document.get("sets"), list):
        raise ValueError("Dokument musi zawierać listę sets.")
    if not document["sets"]:
        raise ValueError("Plik nie zawiera zestawów.")
    by_number = {q.number: q.question_id for q in questions}
    prepared = []
    for position, item in enumerate(document["sets"], 1):
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not item["name"].strip()
        ):
            raise ValueError(f"Zestaw {position}: podaj nazwę.")
        numbers = item.get("question_numbers")
        if not isinstance(numbers, list) or not numbers:
            raise ValueError(f"Zestaw {position}: brak listy question_numbers.")
        if any(type(number) is not int or number < 1 for number in numbers):
            raise ValueError(
                f"Zestaw {position}: numery pytań muszą być dodatnie i całkowite."
            )
        if len(numbers) != len(set(numbers)):
            raise ValueError(f"Zestaw {position}: numery pytań nie mogą się powtarzać.")
        missing = [str(number) for number in numbers if number not in by_number]
        if missing:
            raise ValueError(
                f"Zestaw {position}: brak pytań {', '.join(missing)} "
                "w wybranym arkuszu."
            )
        prepared.append(
            (item["name"].strip(), [by_number[number] for number in numbers])
        )
    return prepared


def required_text(item, key):
    value = item.get(key) if isinstance(item, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Brak tekstowego pola {key} w objaśnieniach.")
    return value.strip()


def prepare_explanations(
    path: Path, questions: list[Question]
) -> list[tuple[int, str]]:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict) or not all(
        isinstance(document.get(key), list) for key in ("acts", "questions")
    ):
        raise ValueError("Plik objaśnień musi zawierać listy acts i questions.")
    if not document["questions"]:
        raise ValueError("Plik nie zawiera objaśnień.")
    legal_date = required_text(document, "legal_status_as_of")
    acts = {}
    for act in document["acts"]:
        act_id = required_text(act, "id")
        if act_id in acts:
            raise ValueError(f"Powtórzony identyfikator aktu: {act_id}.")
        acts[act_id] = (
            required_text(act, "title") + "\n" + required_text(act, "publication")
        )
    by_number = {question.number: question.question_id for question in questions}
    prepared = []
    seen = set()
    for position, item in enumerate(document["questions"], 1):
        if not isinstance(item, dict):
            raise ValueError(f"Objaśnienie {position}: nieprawidłowy wpis.")
        number = item.get("number")
        if type(number) is not int or number not in by_number or number in seen:
            raise ValueError(
                f"Objaśnienie {position}: numer jest nieznany lub powtórzony."
            )
        notes, provisions = item.get("notes"), item.get("provisions")
        if not isinstance(notes, list) or any(
            not isinstance(note, str) for note in notes
        ):
            raise ValueError(f"Objaśnienie {position}: notes musi być listą tekstów.")
        if not isinstance(provisions, list) or not provisions:
            raise ValueError(f"Objaśnienie {position}: brak przepisów w provisions.")
        paragraphs = list(notes)
        for provision in provisions:
            act_id = required_text(provision, "act_id")
            if act_id not in acts:
                raise ValueError(f"Objaśnienie {position}: nieznany akt {act_id}.")
            paragraphs.extend(
                [
                    acts[act_id] + " — " + required_text(provision, "unit"),
                    required_text(provision, "text"),
                ]
            )
            scope = provision.get("text_scope", "")
            if not isinstance(scope, str):
                raise ValueError(
                    f"Objaśnienie {position}: text_scope musi być tekstem."
                )
            if scope:
                paragraphs.append("Zakres cytatu: " + scope)
            urls = provision.get("source_urls")
            if (
                not isinstance(urls, list)
                or not urls
                or any(not isinstance(url, str) or not url.strip() for url in urls)
            ):
                raise ValueError(
                    f"Objaśnienie {position}: brak poprawnych source_urls."
                )
            paragraphs.extend("Źródło: " + url for url in urls)
        paragraphs.append("Stan prawny w pliku: " + legal_date)
        prepared.append((by_number[number], "\n\n".join(paragraphs)))
        seen.add(number)
    return prepared
