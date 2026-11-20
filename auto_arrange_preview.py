from pathlib import Path
from collections import defaultdict
import sys

from PyQt6.QtWidgets import (
    QApplication, QDialog, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QFrame, QScrollArea
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import arrange


class ArrangePreview(QDialog):
    def __init__(self, groups, total_files):
        super().__init__()

        self.setWindowTitle("Smart File Manager - Arrange Preview")
        self.setFixedWidth(720)

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
                padding: 11px 22px;
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

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 22, 24, 20)
        main_layout.setSpacing(16)

        # Header
        header = QHBoxLayout()

        icon = QLabel("📁")
        icon.setFont(QFont("Sans Serif", 27))

        title_box = QVBoxLayout()

        title = QLabel("Arrange Preview")
        title.setFont(QFont("Sans Serif", 19, QFont.Weight.Bold))

        subtitle = QLabel("Review where your selected files will be organized.")
        subtitle.setStyleSheet("color: #9CA3AF; font-size: 12px;")

        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        header.addWidget(icon)
        header.addLayout(title_box)
        header.addStretch()

        main_layout.addLayout(header)

        # Summary card
        summary = QFrame()
        summary.setObjectName("Card")

        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(18, 14, 18, 14)

        number = QLabel(str(total_files))
        number.setFont(QFont("Sans Serif", 25, QFont.Weight.Bold))
        number.setStyleSheet("color: #60A5FA;")

        summary_text = QVBoxLayout()

        summary_title = QLabel("Selected Files")
        summary_title.setFont(QFont("Sans Serif", 12, QFont.Weight.Bold))

        summary_subtitle = QLabel("Ready to be organized")
        summary_subtitle.setStyleSheet("color: #9CA3AF; font-size: 11px;")

        summary_text.addWidget(summary_title)
        summary_text.addWidget(summary_subtitle)

        summary_layout.addWidget(number)
        summary_layout.addSpacing(12)
        summary_layout.addLayout(summary_text)
        summary_layout.addStretch()

        main_layout.addWidget(summary)

        # Category heading
        heading = QLabel("ORGANIZATION PLAN")
        heading.setFont(QFont("Sans Serif", 10, QFont.Weight.Bold))
        heading.setStyleSheet("color: #9CA3AF; letter-spacing: 1px;")

        main_layout.addWidget(heading)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(130)
        scroll.setMaximumHeight(340)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 2, 2, 2)
        content_layout.setSpacing(10)

        icons = {
            "Images": "🖼️",
            "Documents": "📄",
            "Audio": "🎵",
            "Videos": "🎬",
            "Code": "💻",
            "Others": "📦"
        }

        for (parent, category), files in sorted(
            groups.items(),
            key=lambda item: (str(item[0][0]), item[0][1])
        ):
            card = QFrame()
            card.setObjectName("Card")

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(15, 12, 15, 12)
            card_layout.setSpacing(7)

            top = QHBoxLayout()

            category_label = QLabel(
                f"{icons.get(category, '📁')}  {category}"
            )
            category_label.setFont(
                QFont("Sans Serif", 12, QFont.Weight.Bold)
            )

            count_label = QLabel(f"{len(files)} file(s)")
            count_label.setStyleSheet("""
                color: #93C5FD;
                background-color: #263449;
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: bold;
            """)

            top.addWidget(category_label)
            top.addStretch()
            top.addWidget(count_label)

            destination_title = QLabel("DESTINATION")
            destination_title.setStyleSheet(
                "color: #9CA3AF; font-size: 9px; font-weight: bold;"
            )

            destination = QLabel(str(parent / category))
            destination.setWordWrap(True)
            destination.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            destination.setStyleSheet(
                "color: #D1D5DB; font-size: 11px;"
            )

            card_layout.addLayout(top)
            card_layout.addWidget(destination_title)
            card_layout.addWidget(destination)

            content_layout.addWidget(card)

        content_layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        # Information
        info = QLabel(
            "ⓘ  Files will be moved only after you confirm this operation."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        main_layout.addWidget(info)

        # Buttons
        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel = QPushButton("Cancel")
        cancel.setObjectName("Cancel")
        cancel.setMinimumWidth(110)
        cancel.clicked.connect(self.reject)

        confirm = QPushButton("✓  Confirm Arrange")
        confirm.setObjectName("Confirm")
        confirm.setMinimumWidth(170)
        confirm.clicked.connect(self.accept)

        buttons.addWidget(cancel)
        buttons.addWidget(confirm)

        main_layout.addLayout(buttons)


def main():
    selected_files = []

    for argument in sys.argv[1:]:
        path = Path(argument).expanduser()

        if path.is_dir():
            selected_files.extend(
                item for item in path.iterdir() if item.is_file()
            )
        elif path.is_file():
            selected_files.append(path)

    selected_files = list(dict.fromkeys(
        path.resolve() for path in selected_files
    ))

    # Never include Smart File Manager's own project files.
    project_root = Path(__file__).resolve().parent
    protected_files = []

    safe_files = []
    for file_path in selected_files:
        try:
            file_path.relative_to(project_root)
            protected_files.append(file_path.name)
        except ValueError:
            safe_files.append(file_path)

    selected_files = safe_files

    if not selected_files:
        raise SystemExit(0)

    groups = defaultdict(list)

    for file_path in selected_files:
        category = arrange.get_category(file_path)
        groups[(file_path.parent, category)].append(file_path)

    app = QApplication(sys.argv[:1])

    dialog = ArrangePreview(groups, len(selected_files))

    if dialog.exec() == QDialog.DialogCode.Accepted:
        arrange.arrange_selected_files(selected_files)


if __name__ == "__main__":
    main()
