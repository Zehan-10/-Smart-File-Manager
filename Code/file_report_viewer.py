#!/usr/bin/env python3

import sys
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QDialog, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QFrame, QScrollArea,
    QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import database


REPORT_FILE = Path.home() / "SmartFileManager_Report.txt"

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

QFrame#BlueCard {
    background-color: #172D4D;
    border: 1px solid #2563EB;
    border-radius: 12px;
}

QFrame#GreenCard {
    background-color: #16352F;
    border: 1px solid #059669;
    border-radius: 12px;
}

QFrame#PurpleCard {
    background-color: #302449;
    border: 1px solid #7C3AED;
    border-radius: 12px;
}

QPushButton {
    border: none;
    border-radius: 8px;
    padding: 11px 20px;
    font-size: 13px;
    font-weight: bold;
}

QPushButton#Export {
    background-color: #2563EB;
    color: white;
}

QPushButton#Export:hover {
    background-color: #1D4ED8;
}

QPushButton#Close {
    background-color: #374151;
    color: #E5E7EB;
}

QPushButton#Close:hover {
    background-color: #4B5563;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollBar:vertical {
    background: #1F2937;
    width: 9px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: #4B5563;
    border-radius: 4px;
    min-height: 25px;
}
"""


def format_size(size):
    size = float(size)

    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.2f} {unit}"
        size /= 1024


def get_file_data(path):
    path = path.resolve()
    stat = path.stat()

    try:
        saved = database.get_file_details(str(path))
    except Exception:
        saved = None

    try:
        arrange_row = database.get_file_arrange_type(str(path))
        arrange_type = (
            arrange_row["arrange_type"] if arrange_row else "Not recorded"
        )
    except Exception:
        arrange_type = "Not recorded"

    data = {
        "name": path.name,
        "type": path.suffix.upper() if path.suffix else "File",
        "size": stat.st_size,
        "location": str(path),
        "modified": datetime.fromtimestamp(
            stat.st_mtime
        ).strftime("%d-%m-%Y %I:%M:%S %p"),
        "category": "Not recorded",
        "original": "Not recorded",
        "arrange_time": "Not arranged yet",
        "arrange_type": arrange_type,
    }

    if saved:
        data["category"] = saved["category"] or "Unknown"
        data["original"] = (
            saved["original_location"] or "Not recorded"
        )
        data["arrange_time"] = (
            saved["arrange_time"] or "Not arranged yet"
        )

    return data


def build_report(selected_paths):
    report_lines = [
        "SMART FILE MANAGER - SELECTED ITEM REPORT",
        "=" * 65,
        "Generated: " + datetime.now().strftime("%d-%m-%Y %I:%M:%S %p"),
        ""
    ]

    items = []
    total_files = 0
    total_folders = 0
    total_size = 0

    def add_file_report(path):
        nonlocal total_files, total_size

        data = get_file_data(path)
        items.append({"kind": "file", "data": data})

        total_files += 1
        total_size += data["size"]

        report_lines.extend([
            "File Name: " + data["name"],
            "Type: " + data["type"],
            "Size: " + str(data["size"]) + " bytes",
            "Current Location: " + data["location"],
            "Modified Time: " + data["modified"],
            "Category: " + data["category"],
            "Original Location: " + data["original"],
            "Arrange Time: " + data["arrange_time"],
            "Arrange Type: " + data["arrange_type"],
            "-" * 65,
            ""
        ])

    if not selected_paths:
        report_lines.append(
            "No file or folder was selected. "
            "Please select an item in Files and run again."
        )

    for selected in selected_paths:
        report_lines.extend([
            "Selected Item: " + str(selected),
            "=" * 65,
            ""
        ])

        if not selected.exists():
            items.append({
                "kind": "error",
                "name": str(selected),
                "message": "Item does not exist."
            })
            report_lines.extend(["Item does not exist.", ""])
            continue

        if selected.is_file():
            try:
                add_file_report(selected)
            except (OSError, KeyError, TypeError) as error:
                items.append({
                    "kind": "error",
                    "name": selected.name,
                    "message": str(error)
                })
            continue

        if selected.is_dir():
            try:
                children = sorted(
                    selected.iterdir(),
                    key=lambda p: (not p.is_dir(), p.name.lower())
                )
            except OSError as error:
                items.append({
                    "kind": "error",
                    "name": selected.name,
                    "message": str(error)
                })
                report_lines.extend([
                    "Could not read folder: " + str(error), ""
                ])
                continue

            folders = [p for p in children if p.is_dir()]
            files = [p for p in children if p.is_file()]

            total_folders += len(folders)

            items.append({
                "kind": "folder",
                "name": selected.name,
                "location": str(selected.resolve()),
                "count": len(children),
                "files": len(files),
                "folders": len(folders)
            })

            report_lines.extend([
                "Folder Name: " + selected.name,
                "Folder Location: " + str(selected.resolve()),
                "Total Items: " + str(len(children)),
                "",
                "FOLDER CONTENTS",
                "-" * 65,
            ])

            for folder in folders:
                items.append({
                    "kind": "subfolder",
                    "name": folder.name,
                    "location": str(folder)
                })

                report_lines.extend([
                    "Folder: " + folder.name,
                    "Details: Subfolder contents are not included.",
                    "-" * 65,
                    ""
                ])

            for file_path in files:
                try:
                    add_file_report(file_path)
                except (OSError, KeyError, TypeError) as error:
                    items.append({
                        "kind": "error",
                        "name": file_path.name,
                        "message": str(error)
                    })

                    report_lines.extend([
                        "File: " + file_path.name,
                        "Could not read details: " + str(error),
                        "-" * 65,
                        ""
                    ])

    report_text = "\n".join(report_lines)

    return {
        "items": items,
        "files": total_files,
        "folders": total_folders,
        "size": total_size,
        "text": report_text
    }


class FileReportViewer(QDialog):

    def __init__(self, report):
        super().__init__()

        self.report = report

        self.setWindowTitle("Smart File Manager - File Report")
        self.resize(900, 760)
        self.setMinimumSize(680, 550)
        self.setStyleSheet(STYLE)

        main = QVBoxLayout(self)
        main.setContentsMargins(25, 22, 25, 20)
        main.setSpacing(15)

        # Header
        header = QHBoxLayout()

        icon = QLabel("📊")
        icon.setFont(QFont("Sans Serif", 30))

        title_box = QVBoxLayout()

        title = QLabel("File Report")
        title.setFont(QFont("Sans Serif", 21, QFont.Weight.Bold))

        subtitle = QLabel(
            "Detailed information about your selected files and folders."
        )
        subtitle.setStyleSheet("color: #9CA3AF; font-size: 12px;")

        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        header.addWidget(icon)
        header.addLayout(title_box)
        header.addStretch()

        main.addLayout(header)

        # Summary
        summary = QHBoxLayout()
        summary.setSpacing(12)

        self.add_summary_card(
            summary, "📄", "Total Files",
            str(report["files"]), "BlueCard", "#60A5FA"
        )

        self.add_summary_card(
            summary, "📁", "Folders",
            str(report["folders"]), "GreenCard", "#34D399"
        )

        self.add_summary_card(
            summary, "💾", "Total Size",
            format_size(report["size"]), "PurpleCard", "#C4B5FD"
        )

        main.addLayout(summary)

        heading = QLabel("REPORT DETAILS")
        heading.setFont(QFont("Sans Serif", 10, QFont.Weight.Bold))
        heading.setStyleSheet(
            "color: #9CA3AF; letter-spacing: 1px;"
        )

        main.addWidget(heading)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 2, 2, 2)
        content_layout.setSpacing(11)

        for item in report["items"]:
            if item["kind"] == "folder":
                self.add_folder_card(content_layout, item)

            elif item["kind"] == "file":
                self.add_file_card(content_layout, item["data"])

            elif item["kind"] == "subfolder":
                self.add_simple_card(
                    content_layout,
                    "📁  " + item["name"],
                    item["location"],
                    "#34D399"
                )

            elif item["kind"] == "error":
                self.add_simple_card(
                    content_layout,
                    "⚠️  " + item["name"],
                    item["message"],
                    "#F87171"
                )

        if not report["items"]:
            self.add_simple_card(
                content_layout,
                "No items selected",
                "Select files or folders in Nautilus and try again.",
                "#FBBF24"
            )

        content_layout.addStretch()
        scroll.setWidget(content)
        main.addWidget(scroll, 1)

        # Footer
        footer = QHBoxLayout()

        info = QLabel("Smart File Manager  •  Report")
        info.setStyleSheet("color: #6B7280; font-size: 11px;")

        footer.addWidget(info)
        footer.addStretch()

        export_btn = QPushButton("💾  Export TXT")
        export_btn.setObjectName("Export")
        export_btn.clicked.connect(self.export_report)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("Close")
        close_btn.clicked.connect(self.close)

        footer.addWidget(export_btn)
        footer.addWidget(close_btn)

        main.addLayout(footer)

    def add_summary_card(
        self, layout, icon, heading, value, object_name, value_color
    ):
        card = QFrame()
        card.setObjectName(object_name)

        box = QVBoxLayout(card)
        box.setContentsMargins(15, 13, 15, 13)
        box.setSpacing(7)

        top = QLabel(icon + "  " + heading)
        top.setStyleSheet("color: #D1D5DB; font-size: 14px;")

        number = QLabel(value)
        number.setFont(QFont("Sans Serif", 19, QFont.Weight.Bold))
        number.setStyleSheet(f"color: {value_color};")

        box.addWidget(top)
        box.addWidget(number)

        layout.addWidget(card)

    def add_folder_card(self, layout, item):
        card = QFrame()
        card.setObjectName("Card")

        box = QVBoxLayout(card)
        box.setContentsMargins(16, 13, 16, 13)
        box.setSpacing(7)

        title = QLabel("📁  " + item["name"])
        title.setFont(QFont("Sans Serif", 15, QFont.Weight.Bold))

        location = QLabel(item["location"])
        location.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        location.setWordWrap(True)
        location.setStyleSheet("color: #9CA3AF; font-size: 13px;")

        details = QLabel(
            f"Total Items: {item['count']}     "
            f"Files: {item['files']}     "
            f"Subfolders: {item['folders']}"
        )
        details.setStyleSheet("color: #9CA3AF; font-size: 12px;")

        box.addWidget(title)
        box.addWidget(location)
        box.addWidget(details)

        layout.addWidget(card)

    def add_file_card(self, layout, data):
        card = QFrame()
        card.setObjectName("Card")

        box = QVBoxLayout(card)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(8)

        top = QHBoxLayout()

        icon = QLabel("📄")
        icon.setFont(QFont("Sans Serif", 20))

        title = QLabel(data["name"])
        title.setFont(QFont("Sans Serif", 15, QFont.Weight.Bold))
        title.setWordWrap(True)

        type_label = QLabel(data["type"])
        type_label.setStyleSheet("""
            color: #93C5FD;
            background-color: #263449;
            border-radius: 6px;
            padding: 5px 9px;
            font-size: 10px;
        """)

        top.addWidget(icon)
        top.addWidget(title, 1)
        top.addWidget(type_label)

        box.addLayout(top)

        details = [
            ("💾 Size", format_size(data["size"])),
            ("📂 Category", data["category"]),
            ("📍 Current Location", data["location"]),
            ("🕒 Modified Time", data["modified"]),
            ("↩ Original Location", data["original"]),
            ("📅 Arrange Time", data["arrange_time"]),
            ("⚙ Arrange Type", data["arrange_type"]),
        ]

        for label, value in details:
            row = QHBoxLayout()

            key = QLabel(label)
            key.setFixedWidth(180)
            key.setStyleSheet("""
                color: #9CA3AF;
                font-size: 15px;
                font-weight: bold;
            """)

            val = QLabel(str(value))
            val.setWordWrap(True)
            val.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            val.setStyleSheet(
                "color: #E5E7EB; font-size: 13px;"
            )

            row.addWidget(key)
            row.addWidget(val, 1)

            box.addLayout(row)

        layout.addWidget(card)

    def add_simple_card(self, layout, title_text, detail, color):
        card = QFrame()
        card.setObjectName("Card")

        box = QVBoxLayout(card)
        box.setContentsMargins(15, 12, 15, 12)

        title = QLabel(title_text)
        title.setFont(QFont("Sans Serif", 12, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {color};")

        description = QLabel(detail)
        description.setWordWrap(True)
        description.setStyleSheet(
            "color: #9CA3AF; font-size: 13px;"
        )

        box.addWidget(title)
        box.addWidget(description)

        layout.addWidget(card)

    def export_report(self):
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export File Report",
            str(REPORT_FILE),
            "Text Report (*.txt)"
        )

        if not filename:
            return

        if not filename.lower().endswith(".txt"):
            filename += ".txt"

        try:
            Path(filename).write_text(
                self.report["text"],
                encoding="utf-8"
            )

            QMessageBox.information(
                self,
                "Report Exported",
                "Report saved successfully:\n" + filename
            )

        except OSError as error:
            QMessageBox.critical(
                self,
                "Export Error",
                str(error)
            )


def main():
    selected_paths = [
        Path(p).expanduser() for p in sys.argv[1:]
    ]

    report = build_report(selected_paths)

    # Automatically save the original report file.
    try:
        REPORT_FILE.write_text(
            report["text"],
            encoding="utf-8"
        )
    except OSError as error:
        print("Could not save report:", error)

    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)

    window = FileReportViewer(report)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
