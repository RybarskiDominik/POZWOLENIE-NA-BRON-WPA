"""Kopiowanie plików pytań i materiałów z obsługą konfliktów."""

import shutil
from pathlib import Path


def copy_file(source, destination, parent=None):
    from .file_conflict_dialog import FileConflictDialog

    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.is_dir():
        destination /= source.name
    if source == destination:
        return True
    if destination.exists():
        dialog = FileConflictDialog(str(destination), parent)
        dialog.exec()
        if dialog.selected_action == "skip":
            return True
        if dialog.selected_action == "cancel":
            return False
        if dialog.selected_action == "rename":
            original = destination
            counter = 1
            while destination.exists():
                destination = original.with_stem(f"{original.stem}_{counter}")
                counter += 1
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True
