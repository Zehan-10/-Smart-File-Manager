from pathlib import Path
import shutil
import subprocess
import sys

from PyQt6.QtWidgets import (
    QApplication, QDialog, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QFrame, QScrollArea, QWidget
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

import database


class UndoPreview(QDialog):
    def __init__(self, rows):
        super().__init__()

        self.setWindowTitle("Smart File Manager - Undo Preview")
        self.setFixedSize(720, 570)

        self.setStyleSheet("""
            QDialog {
                background-color: #111827;
                color: #F9FAFB;
            }
            QLabel {
                color: #F9FAFB;
                background: transparent;
            }
            QFrame#Card {
                background-color: #1F2937;
                border: 1px solid #374151;
                border-radius: 12px;
            }
            QPushButton {
                border: none;
                border-radius: 8px;
                padding: 11px 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton#Cancel {
                background-color: #374151;
                color: #E5E7EB;
            }
            QPushButton#Cancel:hover {
                background-color: #4B5563;
            }
            QPushButton#Confirm {
                background-color: #2563EB;
                color: white;
            }
            QPushButton#Confirm:hover {
                background-color: #1D4ED8;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(15)

        # Header
        header = QHBoxLayout()

        icon = QLabel("↩")
        icon.setFont(QFont("Sans Serif", 30, QFont.Weight.Bold))
        icon.setStyleSheet("color: #60A5FA;")

        title_box = QVBoxLayout()

        title = QLabel("Undo Last Arrange")
        title.setFont(QFont("Sans Serif", 19, QFont.Weight.Bold))

        subtitle = QLabel("Review the files before restoring them.")
        subtitle.setStyleSheet("color: #9CA3AF; font-size: 12px;")

        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        header.addWidget(icon)
        header.addLayout(title_box)
        header.addStretch()

        layout.addLayout(header)

        # Summary
        summary = QFrame()
        summary.setObjectName("Card")

        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(18, 13, 18, 13)

        number = QLabel(str(len(rows)))
        number.setFont(QFont("Sans Serif", 25, QFont.Weight.Bold))
        number.setStyleSheet("color: #60A5FA;")

        summary_text = QVBoxLayout()

        summary_title = QLabel("Files to Restore")
        summary_title.setFont(QFont("Sans Serif", 12, QFont.Weight.Bold))

        arrange_type = rows[0]["arrange_type"] or "Arrangement"
        summary_subtitle = QLabel(f"Operation: {arrange_type}")
        summary_subtitle.setStyleSheet("color: #9CA3AF; font-size: 11px;")

        summary_text.addWidget(summary_title)
        summary_text.addWidget(summary_subtitle)

        summary_layout.addWidget(number)
        summary_layout.addSpacing(12)
        summary_layout.addLayout(summary_text)
        summary_layout.addStretch()

        layout.addWidget(summary)

        heading = QLabel("RESTORE DETAILS")
        heading.setFont(QFont("Sans Serif", 10, QFont.Weight.Bold))
        heading.setStyleSheet("color: #9CA3AF; letter-spacing: 1px;")

        layout.addWidget(heading)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 2, 2, 2)
        content_layout.setSpacing(9)

        for row in rows:
            card = QFrame()
            card.setObjectName("Card")

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 11, 14, 11)
            card_layout.setSpacing(6)

            name = QLabel(f"📄  {row['file_name']}")
            name.setFont(QFont("Sans Serif", 11, QFont.Weight.Bold))
            name.setWordWrap(True)

            source_title = QLabel("CURRENT LOCATION")
            source_title.setStyleSheet(
                "color: #9CA3AF; font-size: 9px; font-weight: bold;"
            )

            source = QLabel(str(row["destination_location"]))
            source.setWordWrap(True)
            source.setStyleSheet("color: #D1D5DB; font-size: 10px;")

            destination_title = QLabel("RESTORE TO")
            destination_title.setStyleSheet(
                "color: #60A5FA; font-size: 9px; font-weight: bold;"
            )

            destination = QLabel(str(row["original_location"]))
            destination.setWordWrap(True)
            destination.setStyleSheet("color: #93C5FD; font-size: 10px;")

            card_layout.addWidget(name)
            card_layout.addWidget(source_title)
            card_layout.addWidget(source)
            card_layout.addWidget(destination_title)
            card_layout.addWidget(destination)

            content_layout.addWidget(card)

        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        info = QLabel(
            "ⓘ Files will return to their original locations after confirmation."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        layout.addWidget(info)

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setObjectName("Cancel")
        cancel.clicked.connect(self.reject)

        confirm = QPushButton("↩  Confirm Undo")
        confirm.setObjectName("Confirm")
        confirm.clicked.connect(self.accept)

        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)


def notify(message):
    subprocess.run([
        "notify-send", "Smart File Manager", message
    ])


def main():
    rows = database.get_latest_undoable_operation()

    if not rows:
        notify("No arrangement available to undo.")
        return

    # Validate every file before showing or performing Undo.
    conflicts = []

    for row in rows:
        destination = Path(
            row["destination_location"]
        ).expanduser()

        original = Path(
            row["original_location"]
        ).expanduser()

        if not destination.is_file():
            conflicts.append(
                f"{row['file_name']}: Current file is missing."
            )
        elif original.exists():
            conflicts.append(
                f"{row['file_name']}: Original location already exists."
            )

    if conflicts:
        message = (
            "Undo cancelled. No files were moved because "
            "some files have conflicts.\\n\\n"
            + "\\n".join(conflicts[:8])
        )
        notify(message)
        print(message)
        return

    app = QApplication(sys.argv[:1])
    dialog = UndoPreview(rows)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    # Validate again in case files changed while the preview was open.
    for row in rows:
        destination = Path(
            row["destination_location"]
        ).expanduser()

        original = Path(
            row["original_location"]
        ).expanduser()

        if not destination.is_file() or original.exists():
            notify(
                "Undo cancelled: file locations changed. "
                "No files were moved."
            )
            return

    restored = 0
    errors = []

    for row in rows:
        destination = Path(
            row["destination_location"]
        ).expanduser()

        original = Path(
            row["original_location"]
        ).expanduser()

        try:
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(original))

            try:
                database.update_file_location_after_undo(
                    str(destination), str(original)
                )
                database.mark_history_as_undone(row["id"])
            except Exception:
                shutil.move(str(original), str(destination))
                raise

            restored += 1

        except Exception as error:
            errors.append(f"{row['file_name']}: {error}")
            break

    message = f"Successfully restored {restored} file(s)."

    if errors:
        message += "\\nUndo stopped because of an error:\\n"
        message += "\\n".join(errors)

    notify(message)




if __name__ == "__main__":
    main()
