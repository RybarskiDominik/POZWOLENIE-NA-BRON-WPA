"""Przeglądanie pytań z objaśnieniami i lokalnych materiałów do nauki."""

import zipfile
from html import escape
from pathlib import Path
from xml.etree import ElementTree

from PySide6.QtCore import QFile, QIODevice, Qt
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..paths import MATERIALS_DIRECTORY
from ..study import load_settings
from .question_view import highlight_difficult_questions, show_question_details

MATERIALS_PATH = MATERIALS_DIRECTORY
WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_to_html(path):
    def render(node):
        tag = node.tag.removeprefix(WORD_NAMESPACE)
        if tag == "t":
            return escape(node.text or "")
        if tag == "tab":
            return "&emsp;"
        if tag in ("br", "cr"):
            return "<br>"
        if tag in ("footnoteReference", "endnoteReference"):
            return f"<sup>{escape(node.get(WORD_NAMESPACE + 'id', ''))}</sup>"
        content = "".join(render(child) for child in node)
        if tag == "r":
            for name in ("b", "i", "u"):
                style = node.find(f"{WORD_NAMESPACE}rPr/{WORD_NAMESPACE}{name}")
                if style is not None and style.get(WORD_NAMESPACE + "val") not in (
                    "0",
                    "false",
                    "none",
                ):
                    content = f"<{name}>{content}</{name}>"
        if tag == "p":
            return f"<p>{content or '<br>'}</p>"
        if tag == "tbl":
            return f'<table border="1" cellpadding="5">{content}</table>'
        if tag in ("tr", "tc"):
            html_tag = "tr" if tag == "tr" else "td"
            return f"<{html_tag}>{content}</{html_tag}>"
        return content

    with zipfile.ZipFile(path) as document:
        tree = ElementTree.fromstring(document.read("word/document.xml"))
        body = tree.find(WORD_NAMESPACE + "body")
        if body is None:
            raise ValueError("Dokument Word nie zawiera treści.")
        content = render(body)
        for filename in ("word/footnotes.xml", "word/endnotes.xml"):
            if filename not in document.namelist():
                continue
            notes = ElementTree.fromstring(document.read(filename))
            for note in notes:
                number = note.get(WORD_NAMESPACE + "id", "")
                if number.isdecimal() and int(number) > 0:
                    content += f"<p><b>{number}.</b></p>{render(note)}"
    return f"<html><body>{content}</body></html>"


class StudyWindow(QDialog):
    def __init__(
        self,
        catalog,
        sheet_id=None,
        set_id=None,
        parent=None,
        *,
        materials_path=MATERIALS_PATH,
    ):
        super().__init__(parent, Qt.WindowType.Window)
        self.catalog = catalog
        self.setWindowTitle("Nauka — pytania i materiały")
        self.resize(1380, 850)
        self.setMinimumSize(900, 600)
        layout = QVBoxLayout(self)
        columns = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(columns)
        columns.addWidget(self.build_questions_panel())
        columns.addWidget(self.build_materials_panel(materials_path))
        columns.setChildrenCollapsible(False)
        columns.setSizes([600, 740])
        for identifier, name in self.catalog.sheets():
            self.sheet_selector.addItem(name, identifier)
        index = self.sheet_selector.findData(sheet_id)
        self.sheet_selector.setCurrentIndex(index if index >= 0 else 0)
        self.sheet_selector.setEnabled(self.sheet_selector.count() > 0)
        self.sheet_selector.currentIndexChanged.connect(lambda: self.reload_sets())
        self.set_selector.currentIndexChanged.connect(self.show_questions)
        self.search.textChanged.connect(self.filter_questions)
        self.questions.currentItemChanged.connect(self.show_details)
        self.material_selector.currentIndexChanged.connect(self.open_material)
        self.material_zoom.currentIndexChanged.connect(self.set_material_zoom)
        self.reload_sets(set_id)

    def build_questions_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        selection = QFormLayout()
        self.sheet_selector = QComboBox()
        self.set_selector = QComboBox()
        selection.addRow("Arkusz", self.sheet_selector)
        selection.addRow("Zestaw", self.set_selector)
        layout.addLayout(selection)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Szukaj numeru lub treści pytania…")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        questions_panel = QSplitter(Qt.Orientation.Vertical)
        self.questions = QListWidget()
        self.questions.setWordWrap(True)
        self.questions.setResizeMode(QListView.ResizeMode.Adjust)
        self.questions.setAccessibleName("Pytania do nauki")
        questions_panel.addWidget(self.questions)
        explanation_panel = QWidget()
        explanation_layout = QVBoxLayout(explanation_panel)
        explanation_layout.setContentsMargins(0, 0, 0, 0)
        explanation_layout.addWidget(QLabel("Odpowiedzi i objaśnienia"))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Wybierz pytanie z listy powyżej.")
        explanation_layout.addWidget(self.details)
        questions_panel.addWidget(explanation_panel)
        questions_panel.setSizes([330, 400])
        layout.addWidget(questions_panel, 1)
        return panel

    def build_materials_panel(self, materials_path):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("Materiały"))
        self.material_selector = QComboBox()
        self.material_selector.setAccessibleName("Wybierz materiał do nauki")
        self.material_selector.setMinimumWidth(0)
        self.material_selector.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.material_selector.addItem("Wybierz materiał…", None)
        self.load_materials(materials_path)
        layout.addWidget(self.material_selector)
        self.material_zoom = QComboBox()
        self.material_zoom.setAccessibleName("Powiększenie PDF")
        self.material_zoom.addItems(
            ["Dopasuj szerokość", "Cała strona", "100%", "125%", "150%", "200%"]
        )
        self.material_zoom.setEnabled(False)
        layout.addWidget(self.material_zoom)
        self.material_view = QStackedWidget()
        self.material_text = QTextBrowser()
        self.material_text.setOpenExternalLinks(True)
        self.material_text.setPlainText("Wybierz materiał z listy powyżej.")
        self.material_view.addWidget(self.material_text)
        self.pdf_document = QPdfDocument(self)
        self.pdf_file = QFile(self)
        self.pdf_view = QPdfView()
        self.pdf_view.setDocument(self.pdf_document)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.material_view.addWidget(self.pdf_view)
        layout.addWidget(self.material_view, 1)
        return panel

    def load_materials(self, materials_path):
        groups = {
            "opracowania": "Opracowania",
            "ustawy_i_rozporzadzenia": "Ustawy i rozporządzenia",
        }
        for path in sorted(materials_path.rglob("*")):
            if (
                not path.is_file()
                or path.suffix.lower() not in (".pdf", ".docx", ".md")
                or path.name.casefold() == "agents.md"
            ):
                continue
            group = groups.get(path.parent.name, path.parent.name.replace("_", " "))
            title = path.stem.replace("_", " ").capitalize()
            self.material_selector.addItem(
                f"{group} / {title} [{path.suffix[1:].upper()}]", str(path)
            )

    def reload_sets(self, set_id=None):
        sheet_id = self.sheet_selector.currentData()
        if sheet_id is not None and set_id is None:
            set_id = load_settings(self.catalog.database, sheet_id).set_id
        self.set_selector.blockSignals(True)
        self.set_selector.clear()
        for identifier, name in self.catalog.sets(sheet_id):
            self.set_selector.addItem(name, identifier)
        index = self.set_selector.findData(set_id)
        self.set_selector.setCurrentIndex(index if index >= 0 else 0)
        self.set_selector.setEnabled(sheet_id is not None)
        self.set_selector.blockSignals(False)
        self.show_questions()

    def show_questions(self):
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.questions.clear()
        self.details.clear()
        for question in self.catalog.questions(
            self.sheet_selector.currentData(), self.set_selector.currentData()
        ):
            item = QListWidgetItem(f"{question.number}. {question.text}")
            item.setData(Qt.ItemDataRole.UserRole, question)
            self.questions.addItem(item)
        self.refresh_difficulty()
        self.questions.setCurrentRow(0)

    def refresh_difficulty(self):
        flags = self.catalog.flags(self.sheet_selector.currentData())
        highlight_difficult_questions(self.questions, flags)

    def filter_questions(self):
        text = self.search.text().strip().casefold()
        visible = []
        for index in range(self.questions.count()):
            item = self.questions.item(index)
            item.setHidden(text not in item.text().casefold())
            if not item.isHidden():
                visible.append(index)
        if self.questions.currentRow() not in visible:
            self.questions.setCurrentRow(visible[0] if visible else -1)

    def show_details(self, item):
        question = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        show_question_details(self.details, question, include_explanation=True)

    def open_material(self):
        self.reset_material_view()
        filename = self.material_selector.currentData()
        if filename is None:
            self.material_text.setPlainText("Wybierz materiał z listy powyżej.")
            return
        path = Path(filename)
        try:
            if path.suffix.lower() == ".pdf":
                self.open_pdf(path)
            elif path.suffix.lower() == ".docx":
                self.material_text.setHtml(docx_to_html(path))
            else:
                self.material_text.setMarkdown(path.read_text(encoding="utf-8"))
        except (
            OSError,
            ValueError,
            KeyError,
            zipfile.BadZipFile,
            ElementTree.ParseError,
        ) as error:
            self.reset_material_view()
            self.material_text.setPlainText(
                f"Nie udało się otworzyć materiału: {error}"
            )

    def reset_material_view(self):
        self.pdf_document.close()
        self.pdf_file.close()
        self.material_text.clear()
        self.material_view.setCurrentWidget(self.material_text)
        self.material_zoom.setEnabled(False)

    def open_pdf(self, path):
        self.pdf_file.setFileName(str(path))
        if not self.pdf_file.open(QIODevice.OpenModeFlag.ReadOnly):
            raise OSError(self.pdf_file.errorString())
        self.pdf_document.load(self.pdf_file)
        error = self.pdf_document.error()
        if error != QPdfDocument.Error.None_:
            raise ValueError(f"Nie można wczytać PDF: {error.name}.")
        self.material_view.setCurrentWidget(self.pdf_view)
        self.material_zoom.setEnabled(True)
        self.set_material_zoom()

    def set_material_zoom(self):
        index = self.material_zoom.currentIndex()
        if index < 2:
            self.pdf_view.setZoomMode(
                QPdfView.ZoomMode.FitToWidth
                if index == 0
                else QPdfView.ZoomMode.FitInView
            )
        else:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
            self.pdf_view.setZoomFactor(
                int(self.material_zoom.currentText().rstrip("%")) / 100
            )

    def done(self, result):
        self.pdf_document.close()
        self.pdf_file.close()
        super().done(result)
