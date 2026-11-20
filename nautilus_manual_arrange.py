#!/usr/bin/env python3

import sys
import json
from pathlib import Path
from collections import defaultdict

from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog,
    QScrollArea, QWidget, QFrame, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from arrange import move_file_to_destination


RULES_FILE = Path.home() / ".local/share/smart-file-manager/manual_rules.json"


STYLE = """
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
QLineEdit {
    background-color: #111827;
    color: #F9FAFB;
    border: 1px solid #4B5563;
    border-radius: 7px;
    padding: 9px 11px;
    font-size: 11px;
}
QLineEdit:focus {
    border: 1px solid #3B82F6;
}
QPushButton {
    border: none;
    border-radius: 8px;
    padding: 10px 17px;
    font-size: 12px;
    font-weight: bold;
}
QPushButton#Browse {
    background-color: #374151;
    color: #E5E7EB;
}
QPushButton#Browse:hover {
    background-color: #4B5563;
}
QPushButton#Cancel {
    background-color: #374151;
    color: #E5E7EB;
}
QPushButton#Cancel:hover {
    background-color: #4B5563;
}
QPushButton#Primary {
    background-color: #2563EB;
    color: white;
}
QPushButton#Primary:hover {
    background-color: #1D4ED8;
}
QScrollArea {
    border: none;
    background: transparent;
}
"""


class ConfirmPreview(QDialog):
    def __init__(self, groups, destinations):
        super().__init__()

        self.setWindowTitle("Manual Arrange - Preview")
        self.resize(700, 570)
        self.setStyleSheet(STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(15)

        header = QHBoxLayout()

        icon = QLabel("📂")
        icon.setFont(QFont("Sans Serif", 28))

        title_box = QVBoxLayout()

        title = QLabel("Manual Arrange Preview")
        title.setFont(QFont("Sans Serif", 19, QFont.Weight.Bold))

        subtitle = QLabel("Review all file destinations before moving.")
        subtitle.setStyleSheet("color: #9CA3AF; font-size: 12px;")

        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        header.addWidget(icon)
        header.addLayout(title_box)
        header.addStretch()

        layout.addLayout(header)

        total = sum(len(files) for files in groups.values())

        summary = QFrame()
        summary.setObjectName("Card")

        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(17, 13, 17, 13)

        number = QLabel(str(total))
        number.setFont(QFont("Sans Serif", 25, QFont.Weight.Bold))
        number.setStyleSheet("color: #60A5FA;")

        summary_text = QVBoxLayout()

        summary_title = QLabel("Selected Files")
        summary_title.setFont(QFont("Sans Serif", 12, QFont.Weight.Bold))

        summary_subtitle = QLabel(
            f"{len(groups)} file type(s) will be organized"
        )
        summary_subtitle.setStyleSheet("color: #9CA3AF; font-size: 11px;")

        summary_text.addWidget(summary_title)
        summary_text.addWidget(summary_subtitle)

        summary_layout.addWidget(number)
        summary_layout.addSpacing(12)
        summary_layout.addLayout(summary_text)
        summary_layout.addStretch()

        layout.addWidget(summary)

        heading = QLabel("FILE DESTINATION DETAILS")
        heading.setFont(QFont("Sans Serif", 10, QFont.Weight.Bold))
        heading.setStyleSheet("color: #9CA3AF; letter-spacing: 1px;")

        layout.addWidget(heading)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 2, 2, 2)
        content_layout.setSpacing(9)

        for extension, files in sorted(groups.items()):
            card = QFrame()
            card.setObjectName("Card")

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.setSpacing(7)

            top = QHBoxLayout()

            ext_label = QLabel(f"📄  {extension}")
            ext_label.setFont(QFont("Sans Serif", 12, QFont.Weight.Bold))

            count = QLabel(f"{len(files)} file(s)")
            count.setStyleSheet("""
                color: #93C5FD;
                background-color: #263449;
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: bold;
            """)

            top.addWidget(ext_label)
            top.addStretch()
            top.addWidget(count)

            file_names = QLabel(
                "\n".join(f"• {file.name}" for file in files)
            )
            file_names.setWordWrap(True)
            file_names.setStyleSheet(
                "color: #D1D5DB; font-size: 11px;"
            )

            dest_title = QLabel("DESTINATION FOLDER")
            dest_title.setStyleSheet(
                "color: #9CA3AF; font-size: 9px; font-weight: bold;"
            )

            destination = QLabel(str(destinations[extension]))
            destination.setWordWrap(True)
            destination.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            destination.setStyleSheet(
                "color: #93C5FD; font-size: 11px;"
            )

            card_layout.addLayout(top)
            card_layout.addWidget(file_names)
            card_layout.addWidget(dest_title)
            card_layout.addWidget(destination)

            content_layout.addWidget(card)

        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        info = QLabel(
            "ⓘ Only the selected files will be moved after confirmation."
        )
        info.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        layout.addWidget(info)

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setObjectName("Cancel")
        cancel.clicked.connect(self.reject)

        confirm = QPushButton("✓  Confirm Manual Arrange")
        confirm.setObjectName("Primary")
        confirm.clicked.connect(self.accept)

        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)


class ManualArrangeDialog(QDialog):
    def __init__(self, files):
        super().__init__()

        self.setWindowTitle("Smart File Manager - Manual Arrange")
        self.resize(760, 600)
        self.setMinimumSize(650, 500)
        self.setStyleSheet(STYLE)

        self.files = [
            Path(f).expanduser().resolve()
            for f in files
            if Path(f).expanduser().is_file()
        ]

        self.groups = defaultdict(list)

        for file_path in self.files:
            extension = file_path.suffix.lower() or "(No extension)"
            self.groups[extension].append(file_path)

        self.destination_inputs = {}
        self.rules = self.load_rules()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(15)

        header = QHBoxLayout()

        icon = QLabel("🗂️")
        icon.setFont(QFont("Sans Serif", 29))

        title_box = QVBoxLayout()

        title = QLabel("Manual Arrange")
        title.setFont(QFont("Sans Serif", 20, QFont.Weight.Bold))

        subtitle = QLabel(
            "Choose where each type of selected file should be stored."
        )
        subtitle.setStyleSheet("color: #9CA3AF; font-size: 12px;")

        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        header.addWidget(icon)
        header.addLayout(title_box)
        header.addStretch()

        layout.addLayout(header)

        total = len(self.files)

        summary = QFrame()
        summary.setObjectName("Card")

        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(16, 12, 16, 12)

        number = QLabel(str(total))
        number.setFont(QFont("Sans Serif", 23, QFont.Weight.Bold))
        number.setStyleSheet("color: #60A5FA;")

        summary_text = QVBoxLayout()

        summary_title = QLabel("Selected Files")
        summary_title.setFont(QFont("Sans Serif", 11, QFont.Weight.Bold))

        summary_subtitle = QLabel(
            f"{len(self.groups)} different file type(s)"
        )
        summary_subtitle.setStyleSheet("color: #9CA3AF; font-size: 11px;")

        summary_text.addWidget(summary_title)
        summary_text.addWidget(summary_subtitle)

        summary_layout.addWidget(number)
        summary_layout.addSpacing(12)
        summary_layout.addLayout(summary_text)
        summary_layout.addStretch()

        layout.addWidget(summary)

        heading = QLabel("DESTINATION SETTINGS")
        heading.setFont(QFont("Sans Serif", 10, QFont.Weight.Bold))
        heading.setStyleSheet("color: #9CA3AF; letter-spacing: 1px;")

        layout.addWidget(heading)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 2, 2, 2)
        content_layout.setSpacing(11)

        colors = [
            "#60A5FA", "#A78BFA", "#34D399",
            "#FBBF24", "#F472B6", "#FB923C"
        ]

        for index, (extension, grouped_files) in enumerate(
            sorted(self.groups.items())
        ):
            card = QFrame()
            card.setObjectName("Card")

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(15, 13, 15, 13)
            card_layout.setSpacing(9)

            top = QHBoxLayout()

            ext_label = QLabel(f"📄  {extension}")
            ext_label.setFont(QFont("Sans Serif", 12, QFont.Weight.Bold))
            ext_label.setStyleSheet(
                f"color: {colors[index % len(colors)]};"
            )

            count_label = QLabel(
                f"{len(grouped_files)} file(s)"
            )
            count_label.setStyleSheet("""
                color: #93C5FD;
                background-color: #263449;
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: bold;
            """)

            top.addWidget(ext_label)
            top.addStretch()
            top.addWidget(count_label)

            default_parent = grouped_files[0].parent

            default_folder = default_parent / (
                "Manual_NoExtension"
                if extension == "(No extension)"
                else "Manual_" + extension.lstrip(".")
            )

            saved_destination = self.rules.get(extension, "")
            destination = saved_destination or str(default_folder)

            path_row = QHBoxLayout()

            path_input = QLineEdit(destination)
            path_input.setPlaceholderText("Enter destination folder path...")

            browse_button = QPushButton("📁  Browse")
            browse_button.setObjectName("Browse")
            browse_button.clicked.connect(
                lambda checked=False, field=path_input:
                self.browse_folder(field)
            )

            path_row.addWidget(path_input, 1)
            path_row.addWidget(browse_button)

            card_layout.addLayout(top)
            card_layout.addLayout(path_row)

            content_layout.addWidget(card)
            self.destination_inputs[extension] = path_input

        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

        info = QLabel(
            "ⓘ Your destination choices are saved for future Manual Arrange operations."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #9CA3AF; font-size: 11px;")

        layout.addWidget(info)

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setObjectName("Cancel")
        cancel.clicked.connect(self.reject)

        preview_button = QPushButton("✓  Preview and Arrange")
        preview_button.setObjectName("Primary")
        preview_button.clicked.connect(self.preview_and_arrange)

        buttons.addWidget(cancel)
        buttons.addWidget(preview_button)

        layout.addLayout(buttons)

    @staticmethod
    def load_rules():
        try:
            if RULES_FILE.exists():
                with RULES_FILE.open("r", encoding="utf-8") as file:
                    data = json.load(file)
                    return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            pass

        return {}

    def save_rules(self):
        try:
            RULES_FILE.parent.mkdir(parents=True, exist_ok=True)

            with RULES_FILE.open("w", encoding="utf-8") as file:
                json.dump(self.rules, file, indent=2)

        except OSError:
            pass

    def browse_folder(self, path_input):
        current = path_input.text().strip()

        start_folder = (
            current if Path(current).is_dir()
            else str(Path.home())
        )

        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose Destination Folder",
            start_folder
        )

        if folder:
            path_input.setText(folder)

    def preview_and_arrange(self):
        destinations = {}

        for extension, path_input in self.destination_inputs.items():
            text = path_input.text().strip()

            if not text:
                QMessageBox.warning(
                    self,
                    "Destination Required",
                    f"Please choose a destination for {extension}."
                )
                return

            destination = Path(text).expanduser()

            if not destination.is_absolute():
                destination = (
                    self.groups[extension][0].parent / destination
                )

            destinations[extension] = destination.resolve()

        preview = ConfirmPreview(self.groups, destinations)

        if preview.exec() != QDialog.DialogCode.Accepted:
            return

        moved = 0
        errors = []

        for extension, grouped_files in self.groups.items():
            destination = destinations[extension]

            for file_path in grouped_files:
                try:
                    if not file_path.exists():
                        raise FileNotFoundError(
                            "File no longer exists."
                        )

                    if file_path.parent == destination:
                        continue

                    move_file_to_destination(
                        str(file_path),
                        str(destination)
                    )

                    moved += 1

                except Exception as error:
                    errors.append(f"{file_path.name}: {error}")

        for extension, destination in destinations.items():
            self.rules[extension] = str(destination)

        self.save_rules()

        if errors:
            QMessageBox.warning(
                self,
                "Manual Arrange Finished",
                f"Moved: {moved} file(s)\n"
                f"Failed: {len(errors)} file(s)\n\n"
                + "\n".join(errors[:10])
            )
        else:
            QMessageBox.information(
                self,
                "Manual Arrange Finished",
                f"Successfully moved {moved} file(s)."
            )

        self.accept()


def main():
    selected_files = sys.argv[1:]

    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)

    if not selected_files:
        QMessageBox.information(
            None,
            "Manual Arrange",
            "Please select one or more files in Ubuntu Files first."
        )
        return 0

    dialog = ManualArrangeDialog(selected_files)

    if not dialog.files:
        QMessageBox.warning(
            None,
            "Manual Arrange",
            "No valid files were selected."
        )
        return 1

    dialog.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
