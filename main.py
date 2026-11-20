import sys
import os
import html
import sqlite3
import subprocess
import shutil
import zipfile
import stat
import pwd
import grp

from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QDialog,
    QComboBox,
    QDialogButtonBox,
    QInputDialog,
    QFormLayout,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QPushButton,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QSplitter,
    QScrollArea,
    QSizePolicy,
    QProgressBar,
    QCheckBox,
    QGroupBox,
    QGridLayout,
)

from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QFontMetricsF, QDesktopServices
from PyQt6.QtCore import QUrl

import database
import duplicate_finder
import password_manager


# =========================================================
# FILE CATEGORIES
# =========================================================

CATEGORIES = {
    "Images": [
        ".jpg", ".jpeg", ".png", ".gif",
        ".webp", ".bmp", ".svg"
    ],
    "Documents": [
        ".pdf", ".txt", ".doc", ".docx",
        ".xls", ".xlsx", ".ppt", ".pptx",
        ".odt", ".ods"
    ],
    "Audio": [
        ".mp3", ".wav", ".flac",
        ".aac", ".ogg", ".m4a"
    ],
    "Videos": [
        ".mp4", ".mkv", ".avi",
        ".mov", ".wmv", ".webm"
    ],
    "Code": [
        ".py", ".c", ".cpp", ".java",
        ".js", ".html", ".css", ".php",
        ".json", ".xml", ".sh"
    ],
}


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def get_category(path):
    extension = Path(path).suffix.lower()

    for category, extensions in CATEGORIES.items():
        if extension in extensions:
            return category

    return "Others"


def get_size(size):
    if size < 1024:
        return f"{size} B"

    if size < 1024 ** 2:
        return f"{size / 1024:.2f} KB"

    if size < 1024 ** 3:
        return f"{size / (1024 ** 2):.2f} MB"

    return f"{size / (1024 ** 3):.2f} GB"


def format_time(timestamp):
    return (
        datetime.fromtimestamp(timestamp)
        .astimezone()
        .strftime("%d-%m-%Y %I:%M:%S %p %z")
    )


def get_permissions(mode):
    result = ""

    result += "r" if mode & 0o400 else "-"
    result += "w" if mode & 0o200 else "-"
    result += "x" if mode & 0o100 else "-"

    result += "r" if mode & 0o040 else "-"
    result += "w" if mode & 0o020 else "-"
    result += "x" if mode & 0o010 else "-"

    result += "r" if mode & 0o004 else "-"
    result += "w" if mode & 0o002 else "-"
    result += "x" if mode & 0o001 else "-"

    return result


def get_database_details(path):
    try:
        return database.get_file_details(
            str(Path(path).resolve())
        )
    except (sqlite3.Error, OSError):
        return None


def get_created_time(path):
    try:
        stat = Path(path).stat()
        birth_time = getattr(stat, "st_birthtime", None)

        if birth_time is not None:
            return format_time(birth_time)

        return "Not available on this filesystem"

    except OSError:
        return "Not available"


def safe_html(value):
    return html.escape(str(value))



class GlobalSearchWorker(QThread):
    result_found = pyqtSignal(str)
    search_finished = pyqtSignal(int)

    def __init__(self, query, parent=None):
        super().__init__(parent)
        self.query = query.casefold()
        self.count = 0

    def run(self):
        excluded = {"/proc", "/sys", "/dev", "/run"}

        for root, dirs, files in os.walk(
            "/",
            topdown=True,
            followlinks=False,
            onerror=lambda error: None
        ):
            if self.isInterruptionRequested():
                break

            dirs[:] = [
                name for name in dirs
                if str(Path(root) / name) not in excluded
            ]

            for name in dirs + files:
                if self.isInterruptionRequested():
                    break

                path = Path(root) / name

                if (
                    self.query in name.casefold()
                    or (
                        self.query.startswith(".")
                        and path.suffix.casefold() == self.query
                    )
                ):
                    self.result_found.emit(str(path))
                    self.count += 1

        self.search_finished.emit(self.count)



# =========================================================
# EMPTY FOLDER CLEANER
# =========================================================

PROTECTED_EMPTY_SCAN_PATHS = {
    "/proc", "/sys", "/dev", "/run",
    "/usr", "/etc", "/var", "/boot", "/root",
    "/lost+found", "/snap", "/tmp", "/opt", "/srv",
    "/bin", "/sbin", "/lib", "/lib64",
}


def is_safe_empty_scan_path(path):
    try:
        original = Path(path)

        if original.is_symlink():
            return False

        resolved = original.resolve(strict=True)

        if str(resolved) == "/":
            return False

        for protected in PROTECTED_EMPTY_SCAN_PATHS:
            try:
                resolved.relative_to(Path(protected))
                return False
            except ValueError:
                pass

        return (
            not resolved.is_symlink()
            and resolved.is_dir()
        )

    except (OSError, RuntimeError):
        return False


class EmptyFolderScanWorker(QThread):
    folder_found = pyqtSignal(str)
    scan_finished = pyqtSignal(int)
    scan_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.found_count = 0

    def run(self):
        self.scan_message.emit("Scanning the filesystem...")

        for root, dirs, files in os.walk(
            "/",
            topdown=True,
            followlinks=False,
            onerror=lambda error: None
        ):
            if self.isInterruptionRequested():
                break

            kept_dirs = []

            for name in dirs:
                path = os.path.join(root, name)

                if path in PROTECTED_EMPTY_SCAN_PATHS:
                    continue

                if os.path.islink(path):
                    continue

                try:
                    if os.path.ismount(path):
                        continue

                    if not os.access(path, os.R_OK | os.X_OK):
                        continue

                except OSError:
                    continue

                kept_dirs.append(name)

            dirs[:] = kept_dirs

            if root != "/" and not dirs and not files:
                if is_safe_empty_scan_path(root):
                    self.folder_found.emit(root)
                    self.found_count += 1

        self.scan_finished.emit(self.found_count)


class EmptyFolderCleanerDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Empty Folder Cleaner")
        self.resize(850, 580)
        self.setMinimumSize(620, 420)

        self.scan_worker = None
        self.found_paths = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Empty Folder Cleaner")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        info = QLabel(
            "Scan for empty folders on this Ubuntu filesystem. "
            "Protected system locations and mounted drives are skipped."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.status_label = QLabel(
            "Click 'Scan Empty Folders' to start."
        )
        layout.addWidget(self.status_label)

        self.folder_list = QListWidget()
        self.folder_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.folder_list.itemDoubleClicked.connect(
            self.open_folder_location
        )
        layout.addWidget(self.folder_list)

        selection_row = QHBoxLayout()

        self.select_all_button = QPushButton("Select All")
        self.select_all_button.clicked.connect(self.select_all)
        selection_row.addWidget(self.select_all_button)

        self.clear_selection_button = QPushButton("Clear Selection")
        self.clear_selection_button.clicked.connect(
            self.clear_selection
        )
        selection_row.addWidget(self.clear_selection_button)

        selection_row.addStretch()
        layout.addLayout(selection_row)

        action_row = QHBoxLayout()

        self.scan_button = QPushButton("Scan Empty Folders")
        self.scan_button.clicked.connect(self.start_scan)
        action_row.addWidget(self.scan_button)

        self.delete_button = QPushButton("Delete Selected")
        self.delete_button.clicked.connect(self.delete_selected)
        self.delete_button.setEnabled(False)
        action_row.addWidget(self.delete_button)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        action_row.addWidget(self.close_button)

        layout.addLayout(action_row)

        if parent is not None:
            self.setStyleSheet(parent.styleSheet())

    def start_scan(self):
        if self.scan_worker is not None and self.scan_worker.isRunning():
            return

        self.folder_list.clear()
        self.found_paths.clear()

        self.delete_button.setEnabled(False)
        self.scan_button.setEnabled(False)
        self.close_button.setEnabled(False)

        self.status_label.setText("Scanning... Please wait.")

        self.scan_worker = EmptyFolderScanWorker(self)
        self.scan_worker.folder_found.connect(self.add_folder)
        self.scan_worker.scan_message.connect(
            self.status_label.setText
        )
        self.scan_worker.scan_finished.connect(self.scan_complete)
        self.scan_worker.start()

    def open_folder_location(self, item):
        folder_path = item.text()
        path = Path(folder_path)

        if not path.exists() or not path.is_dir():
            QMessageBox.warning(
                self,
                "Folder Not Found",
                "This folder no longer exists."
            )
            return

        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(path))
        )

    def add_folder(self, path):
        if path in self.found_paths:
            return

        self.found_paths.add(path)

        item = QListWidgetItem(path)
        item.setFlags(
            item.flags() | Qt.ItemFlag.ItemIsUserCheckable
        )
        item.setCheckState(Qt.CheckState.Unchecked)

        self.folder_list.addItem(item)

    def scan_complete(self, count):
        self.scan_button.setEnabled(True)
        self.close_button.setEnabled(True)
        self.delete_button.setEnabled(count > 0)

        self.status_label.setText(
            f"Scan complete. Found {count} empty folder(s)."
        )

    def select_all(self):
        for index in range(self.folder_list.count()):
            self.folder_list.item(index).setCheckState(
                Qt.CheckState.Checked
            )

    def clear_selection(self):
        for index in range(self.folder_list.count()):
            self.folder_list.item(index).setCheckState(
                Qt.CheckState.Unchecked
            )

    def delete_selected(self):
        selected_paths = [
            self.folder_list.item(i).text()
            for i in range(self.folder_list.count())
            if self.folder_list.item(i).checkState()
            == Qt.CheckState.Checked
        ]

        if not selected_paths:
            QMessageBox.information(
                self, "No Selection",
                "Please select folders to delete."
            )
            return

        answer = QMessageBox.question(
            self, "Confirm Deletion",
            f"Are you sure you want to delete {len(selected_paths)} "
            "selected empty folder(s)? This action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        deleted_paths = []
        failed_paths = []
        selected_paths.sort(
            key=lambda value: len(Path(value).parts),
            reverse=True
        )

        for folder_path in selected_paths:
            try:
                if not is_safe_empty_scan_path(folder_path):
                    failed_paths.append(
                        (folder_path, "Protected or unsafe location")
                    )
                    continue

                with os.scandir(folder_path) as entries:
                    if next(entries, None) is not None:
                        failed_paths.append(
                            (folder_path, "Folder is not empty")
                        )
                        continue

                os.rmdir(folder_path)
                deleted_paths.append(folder_path)
            except OSError as exc:
                failed_paths.append((folder_path, str(exc)))

        database_error = False
        for folder_path in deleted_paths:
            try:
                database.delete_records_for_deleted_folder(folder_path)
            except (sqlite3.Error, OSError):
                database_error = True

        deleted_set = set(deleted_paths)
        deleted_items = [
            self.folder_list.item(i)
            for i in range(self.folder_list.count())
            if self.folder_list.item(i).text() in deleted_set
        ]

        self.delete_button.setEnabled(False)
        self.scan_button.setEnabled(False)
        self.close_button.setEnabled(False)

        def finish_cleanup():
            for i in reversed(range(self.folder_list.count())):
                item = self.folder_list.item(i)
                if item.text() in deleted_set:
                    self.folder_list.takeItem(i)

            remaining = self.folder_list.count()
            self.scan_button.setEnabled(True)
            self.close_button.setEnabled(True)
            self.delete_button.setEnabled(remaining > 0)

            self.status_label.setText(
                f"Deleted: {len(deleted_paths)} | "
                f"Failed: {len(failed_paths)} | Remaining: {remaining}"
            )

            message = (
                f"Successfully deleted: {len(deleted_paths)} folder(s)."
                f"\nCould not delete: {len(failed_paths)} folder(s)."
            )
            if failed_paths:
                message += "\n\nFailure details (first 10):"
                for folder_path, reason in failed_paths[:10]:
                    message += f"\n\n{folder_path}\nReason: {reason}"
                if len(failed_paths) > 10:
                    message += (
                        f"\n\nAnd {len(failed_paths) - 10} more."
                    )

            if database_error:
                message += (
                    "\n\nWarning: Some database records "
                    "could not be cleaned."
                )
            QMessageBox.information(self, "Cleanup Complete", message)

        if not deleted_items:
            finish_cleanup()
            return

        from PyQt6.QtCore import QVariantAnimation
        from PyQt6.QtGui import QColor, QBrush

        animation = QVariantAnimation(self)
        animation.setDuration(700)
        animation.setStartValue(QColor(46, 204, 113, 0))
        animation.setKeyValueAt(0.4, QColor(46, 204, 113, 190))
        animation.setEndValue(QColor(46, 204, 113, 0))

        def update_rows(color):
            brush = QBrush(color)
            for item in deleted_items:
                if self.folder_list.row(item) >= 0:
                    item.setBackground(brush)

        animation.valueChanged.connect(update_rows)
        animation.finished.connect(finish_cleanup)
        self.delete_animation = animation
        animation.start()



    def closeEvent(self, event):
        if (
            self.scan_worker is not None
            and self.scan_worker.isRunning()
        ):
            QMessageBox.information(
                self,
                "Scan Running",
                "Please wait until the scan is complete."
            )
            event.ignore()
            return

        event.accept()



# =========================================================
# LARGE FILE FINDER
# =========================================================

class DuplicateScanWorker(QThread):

    progress = pyqtSignal(int, str)
    scan_finished = pyqtSignal(object)

    def __init__(self, folder_path, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path

    def run(self):

        results = duplicate_finder.scan_duplicates(
            self.folder_path,
            progress_callback=self.send_progress,
            cancel_check=self.isInterruptionRequested
        )

        self.scan_finished.emit(results)

    def send_progress(self, count, path):
        self.progress.emit(count, path)


class DuplicateTrashWorker(QThread):

    trash_finished = pyqtSignal(object)

    def __init__(self, file_paths, parent=None):
        super().__init__(parent)
        self.file_paths = file_paths

    def run(self):

        moved = 0
        failed = 0
        moved_paths = []

        for file_path in self.file_paths:

            if self.isInterruptionRequested():
                break

            path = Path(file_path)

            try:
                if path.is_symlink() or not path.is_file():
                    failed += 1
                    continue

                resolved = path.resolve(strict=True)

                if str(resolved) == "/" or any(
                    resolved == Path(blocked)
                    or Path(blocked) in resolved.parents
                    for blocked in PROTECTED_EMPTY_SCAN_PATHS
                ):
                    failed += 1
                    continue

                subprocess.run(
                    ["gio", "trash", str(path)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True
                )

                moved += 1
                moved_paths.append(str(path))

            except (OSError, subprocess.CalledProcessError):
                failed += 1

        self.trash_finished.emit({
            "moved": moved,
            "failed": failed,
            "moved_paths": moved_paths
        })


class LargeFileScanWorker(QThread):
    scan_finished = pyqtSignal(object)

    def run(self):
        results = []
        minimum_size = 10 * 1024 * 1024

        excluded = set(PROTECTED_EMPTY_SCAN_PATHS) | {
            "/proc", "/sys", "/dev", "/run"
        }

        for root, dirs, files in os.walk(
            "/", topdown=True, followlinks=False,
            onerror=lambda error: None
        ):
            if self.isInterruptionRequested():
                break

            kept_dirs = []

            for name in dirs:
                folder = os.path.join(root, name)

                if folder in excluded or os.path.islink(folder):
                    continue

                try:
                    if os.path.ismount(folder):
                        continue

                    if not os.access(folder, os.R_OK | os.X_OK):
                        continue
                except OSError:
                    continue

                kept_dirs.append(name)

            dirs[:] = kept_dirs

            for name in files:
                if self.isInterruptionRequested():
                    break

                path = os.path.join(root, name)

                try:
                    if os.path.islink(path):
                        continue

                    stat = os.stat(path, follow_symlinks=False)

                    if stat.st_size >= minimum_size:
                        results.append(
                            (path, stat.st_size, stat.st_mtime)
                        )

                except OSError:
                    continue

        results.sort(key=lambda item: item[1], reverse=True)
        self.scan_finished.emit(results)


class DuplicateFileFinderDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Duplicate File Finder")
        self.resize(1100, 680)
        self.setMinimumSize(800, 500)

        self.worker = None
        self.trash_worker = None
        self.duplicate_groups = []
        self.current_folder = None
        self.trash_animation_timer = QTimer(self)
        self.trash_animation_timer.timeout.connect(
            self.animate_trash_rows
        )
        self.trash_animation_heights = {}

        layout = QVBoxLayout(self)

        title = QLabel("Duplicate File Finder")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        info = QLabel(
            "Find identical files using SHA-256 content matching. "
            "Select files independently and move unwanted copies to Ubuntu Trash."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.status = QLabel(
            "Choose a scan location to find duplicate files."
        )
        layout.addWidget(self.status)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            "File Name",
            "Full Location",
            "Size",
            "Modified Date",
            "Select"
        ])

        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )

        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )

        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )

        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )

        layout.addWidget(self.table)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        buttons = QHBoxLayout()

        self.home_button = QPushButton("Scan Home")
        self.home_button.clicked.connect(
            lambda: self.start_scan(str(Path.home()))
        )
        buttons.addWidget(self.home_button)

        self.folder_button = QPushButton("Choose Folder")
        self.folder_button.clicked.connect(self.choose_folder)
        buttons.addWidget(self.folder_button)

        self.system_button = QPushButton("Scan Full System")
        self.system_button.clicked.connect(
            lambda: self.start_scan("/")
        )
        buttons.addWidget(self.system_button)

        self.select_all_button = QPushButton("Select All")
        self.select_all_button.clicked.connect(self.select_all_files)
        buttons.addWidget(self.select_all_button)

        self.deselect_all_button = QPushButton("Deselect All")
        self.deselect_all_button.clicked.connect(self.deselect_all_files)
        buttons.addWidget(self.deselect_all_button)

        self.scan_again_button = QPushButton("Scan Again")
        self.scan_again_button.clicked.connect(self.scan_again)
        buttons.addWidget(self.scan_again_button)

        self.trash_button = QPushButton("Delete Selected")
        self.trash_button.clicked.connect(
            self.move_unwanted_to_trash
        )
        self.trash_button.setEnabled(False)
        buttons.addWidget(self.trash_button)

        self.cancel_button = QPushButton("Cancel Scan")
        self.cancel_button.clicked.connect(self.cancel_scan)
        self.cancel_button.setEnabled(False)
        buttons.addWidget(self.cancel_button)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)

        layout.addLayout(buttons)

        if parent is not None:
            self.setStyleSheet(parent.styleSheet())


        self.group_rows = []
        self.updating_keep_selection = False

    # -------------------------------------------------
    # CHOOSE FOLDER
    # -------------------------------------------------

    def choose_folder(self):

        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose Folder to Scan",
            str(Path.home())
        )

        if folder:
            self.start_scan(folder)

    # -------------------------------------------------
    # START SCAN
    # -------------------------------------------------

    def start_scan(self, folder_path):

        if self.worker is not None and self.worker.isRunning():
            return

        if self.trash_worker is not None and self.trash_worker.isRunning():
            return

        self.table.setRowCount(0)
        self.group_rows = []
        self.current_folder = str(Path(folder_path).resolve())
        self.trash_button.setEnabled(False)

        self.home_button.setEnabled(False)
        self.folder_button.setEnabled(False)
        self.system_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        self.progress_bar.show()
        self.status.setText(
            f"Scanning: {folder_path} ..."
        )

        self.worker = DuplicateScanWorker(
            folder_path,
            self
        )

        self.worker.progress.connect(self.update_progress)
        self.worker.scan_finished.connect(self.scan_complete)
        self.worker.start()

    # -------------------------------------------------
    # SCAN PROGRESS
    # -------------------------------------------------

    def update_progress(self, count, current_path):

        self.status.setText(
            f"Scanned {count} file(s). Current: {current_path}"
        )

    # -------------------------------------------------
    # SCAN COMPLETE
    # -------------------------------------------------

    def scan_complete(self, results):

        groups = results.get("groups", [])

        self.table.setRowCount(0)
        self.group_rows = []

        total_savings = 0

        for group in groups:

            paths = group["files"]
            size = group["size"]

            if len(paths) < 2:
                continue

            start_row = self.table.rowCount()

            total_savings += size * (len(paths) - 1)

            for index, file_path in enumerate(paths):

                try:
                    file_stat = Path(file_path).stat()

                    modified = datetime.fromtimestamp(
                        file_stat.st_mtime
                    ).strftime("%Y-%m-%d %H:%M")

                except OSError:
                    modified = "Unavailable"

                row = self.table.rowCount()
                self.table.insertRow(row)

                values = [
                    Path(file_path).name,
                    file_path,
                    get_size(size),
                    modified
                ]

                for column, value in enumerate(values):

                    item = QTableWidgetItem(str(value))

                    # Show complete information when mouse hovers.
                    item.setToolTip(str(value))

                    self.table.setItem(row, column, item)

                select_item = QTableWidgetItem()
                select_item.setFlags(
                    select_item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                )
                select_item.setCheckState(Qt.CheckState.Unchecked)
                self.table.setItem(row, 4, select_item)

            end_row = self.table.rowCount() - 1

            self.group_rows.append(
                (start_row, end_row)
            )

        self.home_button.setEnabled(True)
        self.folder_button.setEnabled(True)
        self.system_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

        self.progress_bar.hide()
        self.trash_button.setEnabled(bool(self.group_rows))

        scanned = results.get("scanned", 0)
        skipped = results.get("skipped", 0)

        cancelled = (
            self.worker is not None
            and self.worker.isInterruptionRequested()
        )

        message = (
            f"Scanned {scanned} file(s). "
            f"Found {len(groups)} duplicate group(s). "
            f"Potential space savings: {get_size(total_savings)}. "
            f"Skipped: {skipped}."
        )

        if cancelled:
            message = "Scan cancelled. " + message

        self.status.setText(message)

    # -------------------------------------------------
    # -------------------------------------------------
    # INDEPENDENT FILE SELECTION
    # -------------------------------------------------

    def select_all_files(self):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 4)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked)

    def deselect_all_files(self):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 4)
            if item is not None:
                item.setCheckState(Qt.CheckState.Unchecked)

    def scan_again(self):
        if self.current_folder:
            self.start_scan(self.current_folder)

    # -------------------------------------------------
    # MOVE UNWANTED COPIES TO UBUNTU TRASH
    # -------------------------------------------------

    def move_unwanted_to_trash(self):

        if not self.group_rows:
            return

        if self.trash_worker is not None and self.trash_worker.isRunning():
            return

        unwanted_files = []
        total_size = 0
        preserved_count = 0

        for start_row, end_row in self.group_rows:

            selected_rows = [
                row for row in range(start_row, end_row + 1)
                if self.table.item(row, 4) is not None
                and self.table.item(row, 4).checkState()
                == Qt.CheckState.Checked
            ]

            group_count = end_row - start_row + 1

            if not selected_rows:
                continue

            # Keep one copy if every file in this group is selected.
            if len(selected_rows) == group_count:
                selected_rows.remove(start_row)
                preserved_count += 1

            for row in selected_rows:
                path_item = self.table.item(row, 1)
                if path_item is not None:
                    unwanted_files.append(path_item.text())

        if not unwanted_files:
            QMessageBox.information(
                self, "Nothing Selected",
                "Please select files to move to Ubuntu Trash."
            )
            return

        for file_path in unwanted_files:
            try:
                total_size += Path(file_path).stat().st_size
            except OSError:
                pass

        message = (
            f"Move {len(unwanted_files)} selected file(s) "
            f"({get_size(total_size)}) to Ubuntu Trash?\n\n"
            "Files will not be permanently deleted."
        )

        if preserved_count:
            message += (
                f"\n\nOne copy will automatically be kept in "
                f"{preserved_count} fully selected duplicate group(s)."
            )

        answer = QMessageBox.question(
            self, "Confirm Delete Selected", message,
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self.trash_button.setEnabled(False)
        self.home_button.setEnabled(False)
        self.folder_button.setEnabled(False)
        self.system_button.setEnabled(False)
        self.cancel_button.setEnabled(False)

        self.status.setText(
            f"Moving {len(unwanted_files)} file(s) to Ubuntu Trash... Please wait."
        )

        self.trash_worker = DuplicateTrashWorker(unwanted_files, self)
        self.trash_worker.trash_finished.connect(
            self.trash_operation_complete
        )
        self.trash_worker.start()

    # -------------------------------------------------
    # TRASH OPERATION COMPLETE
    # -------------------------------------------------

    def trash_operation_complete(self, results):

        moved = results.get("moved", 0)
        failed = results.get("failed", 0)
        moved_paths = set(results.get("moved_paths", []))

        self.home_button.setEnabled(True)
        self.folder_button.setEnabled(True)
        self.system_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.trash_button.setEnabled(False)

        QMessageBox.information(
            self,
            "Trash Operation Complete",
            f"Moved to Ubuntu Trash: {moved}\\n"
            f"Failed or protected: {failed}\\n\\n"
            "No files were permanently deleted."
        )

        if not moved_paths:
            self.status.setText(
                f"Moved: 0 | Failed or protected: {failed}"
            )
            return

        rows = []

        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item is not None and item.text() in moved_paths:
                rows.append(row)

        if not rows:
            if self.current_folder:
                self.start_scan(self.current_folder)
            return

        self.trash_animation_heights = {
            row: self.table.rowHeight(row)
            for row in rows
        }

        self.status.setText(
            "Removing files moved to Trash..."
        )

        self.trash_animation_timer.start(15)

    def animate_trash_rows(self):

        finished = True

        for row in self.trash_animation_heights:
            height = self.trash_animation_heights[row]

            if height > 0:
                height = max(0, height - 5)
                self.trash_animation_heights[row] = height
                self.table.setRowHeight(row, height)

            if height > 0:
                finished = False

        if not finished:
            return

        self.trash_animation_timer.stop()

        for row in sorted(self.trash_animation_heights, reverse=True):
            self.table.removeRow(row)

        self.trash_animation_heights.clear()

        if self.current_folder:
            self.status.setText("Refreshing duplicate results...")
            self.start_scan(self.current_folder)


    def cancel_scan(self):

        if self.worker is not None and self.worker.isRunning():

            self.worker.requestInterruption()
            self.cancel_button.setEnabled(False)

            self.status.setText(
                "Cancelling scan... Please wait."
            )

    # -------------------------------------------------
    # CLOSE DIALOG
    # -------------------------------------------------

    def closeEvent(self, event):

        if self.trash_worker is not None and self.trash_worker.isRunning():
            QMessageBox.information(
                self,
                "Trash Operation Running",
                "Files are being moved to Ubuntu Trash. "
                "Please wait until the operation finishes."
            )
            event.ignore()
            return

        if self.worker is not None and self.worker.isRunning():

            self.worker.requestInterruption()

            QMessageBox.information(
                self,
                "Scan Running",
                "Scan cancellation requested. "
                "Please wait until the scan stops."
            )

            event.ignore()
            return

        event.accept()


class LargeFileFinderDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Large File Finder")
        self.resize(1050, 650)
        self.setMinimumSize(750, 480)

        self.worker = None

        layout = QVBoxLayout(self)

        title = QLabel("Large File Finder")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        info = QLabel(
            "Find files of 10 MB or larger. Protected system folders "
            "and mounted drives are skipped. Selected files will be "
            "moved to Ubuntu Trash, not permanently deleted."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.status = QLabel("Click Scan Large Files to begin.")
        layout.addWidget(self.status)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            "File Name", "Location", "Size", "Modified Date"
        ])

        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )

        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )

        self.table.itemDoubleClicked.connect(self.open_file)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()

        self.scan_button = QPushButton("Scan Large Files")
        self.scan_button.clicked.connect(self.start_scan)
        buttons.addWidget(self.scan_button)

        self.delete_button = QPushButton("Move Selected to Trash")
        self.delete_button.clicked.connect(self.delete_selected)
        self.delete_button.setEnabled(False)
        buttons.addWidget(self.delete_button)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)

        layout.addLayout(buttons)

        if parent is not None:
            self.setStyleSheet(parent.styleSheet())

    def start_scan(self):
        if self.worker is not None and self.worker.isRunning():
            return

        self.table.setRowCount(0)
        self.scan_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.status.setText("Scanning... Please wait.")

        self.worker = LargeFileScanWorker(self)
        self.worker.scan_finished.connect(self.scan_complete)
        self.worker.start()

    def scan_complete(self, results):
        self.table.setRowCount(len(results))
        total_size = 0

        for row, (path, size, modified) in enumerate(results):
            total_size += size

            values = [
                Path(path).name,
                path,
                get_size(size),
                datetime.fromtimestamp(modified).strftime(
                    "%Y-%m-%d %H:%M"
                )
            ]

            for column, value in enumerate(values):
                self.table.setItem(
                    row, column, QTableWidgetItem(str(value))
                )

        self.scan_button.setEnabled(True)
        self.delete_button.setEnabled(bool(results))

        self.status.setText(
            f"Found {len(results)} large file(s). "
            f"Combined size: {get_size(total_size)}."
        )

    def open_file(self, item):
        path = Path(self.table.item(item.row(), 1).text())

        if path.is_file():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(path))
            )
        else:
            QMessageBox.warning(
                self, "File Not Found",
                "This file no longer exists."
            )

    def delete_selected(self):
        rows = sorted({
            index.row()
            for index in self.table.selectionModel().selectedRows()
        })

        if not rows:
            QMessageBox.information(
                self, "No Selection",
                "Please select files first."
            )
            return

        paths = [
            self.table.item(row, 1).text()
            for row in rows
        ]

        answer = QMessageBox.question(
            self,
            "Confirm Move to Trash",
            f"Move {len(paths)} selected file(s) to Ubuntu Trash?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        moved = 0
        failed = 0

        for value in paths:
            try:
                path = Path(value)

                if path.is_symlink() or not path.is_file():
                    failed += 1
                    continue

                resolved = path.resolve(strict=True)

                if any(
                    resolved == Path(blocked)
                    or Path(blocked) in resolved.parents
                    for blocked in PROTECTED_EMPTY_SCAN_PATHS
                ):
                    failed += 1
                    continue

                subprocess.run(
                    ["gio", "trash", str(path)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True
                )

                moved += 1

            except (OSError, subprocess.CalledProcessError):
                failed += 1

        QMessageBox.information(
            self,
            "Trash Operation Complete",
            f"Moved to Trash: {moved}\nCould not move: {failed}"
        )

        self.start_scan()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(
                self, "Scan Running",
                "Please wait until scanning is complete."
            )
            event.ignore()
            return

        event.accept()



# =========================================================
# ARCHIVE MANAGER
# =========================================================

class ArchiveManagerDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("ZIP & UNZIP Manager")
        self.resize(750, 520)
        self.setMinimumSize(600, 400)

        self.selected_paths = []

        layout = QVBoxLayout(self)

        title = QLabel("ZIP & UNZIP Manager")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        info = QLabel(
            "Select files or folders to create a ZIP archive, "
            "or extract an existing ZIP file."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        layout.addWidget(self.file_list)

        add_buttons = QHBoxLayout()

        add_files = QPushButton("Add Files")
        add_files.clicked.connect(self.add_files)
        add_buttons.addWidget(add_files)

        add_folder = QPushButton("Add Folder")
        add_folder.clicked.connect(self.add_folder)
        add_buttons.addWidget(add_folder)

        remove_button = QPushButton("Remove Selected")
        remove_button.clicked.connect(self.remove_selected)
        add_buttons.addWidget(remove_button)

        layout.addLayout(add_buttons)

        archive_buttons = QHBoxLayout()

        create_button = QPushButton("Create ZIP")
        create_button.clicked.connect(self.create_zip)
        archive_buttons.addWidget(create_button)

        extract_here = QPushButton("Extract ZIP Here")
        extract_here.clicked.connect(self.extract_here)
        archive_buttons.addWidget(extract_here)

        extract_to = QPushButton("Extract ZIP To...")
        extract_to.clicked.connect(self.extract_to)
        archive_buttons.addWidget(extract_to)

        layout.addLayout(archive_buttons)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)

        self.status = QLabel("Ready")
        layout.addWidget(self.status)

    def refresh_list(self):
        self.file_list.clear()

        for path in self.selected_paths:
            self.file_list.addItem(str(path))

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Files"
        )

        for item in files:
            path = Path(item)

            if path not in self.selected_paths:
                self.selected_paths.append(path)

        self.refresh_list()

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder"
        )

        if folder:
            path = Path(folder)

            if path not in self.selected_paths:
                self.selected_paths.append(path)

            self.refresh_list()

    def remove_selected(self):
        selected = {
            item.text() for item in self.file_list.selectedItems()
        }

        self.selected_paths = [
            path for path in self.selected_paths
            if str(path) not in selected
        ]

        self.refresh_list()

    def create_zip(self):

        if not self.selected_paths:
            QMessageBox.information(
                self, "No Files",
                "Please add files or folders first."
            )
            return

        output, _ = QFileDialog.getSaveFileName(
            self,
            "Save ZIP Archive",
            str(Path.home() / "Archive.zip"),
            "ZIP Archives (*.zip)"
        )

        if not output:
            return

        output_path = Path(output)

        if output_path.suffix.lower() != ".zip":
            output_path = output_path.with_suffix(".zip")

        try:
            with zipfile.ZipFile(
                output_path, "w",
                compression=zipfile.ZIP_DEFLATED
            ) as archive:

                used_names = set()

                for source in self.selected_paths:

                    if not source.exists():
                        continue

                    if source.is_symlink():
                        continue

                    if source.is_file():
                        files = [(source, source.name)]

                    elif source.is_dir():
                        files = []

                        for item in source.rglob("*"):
                            if item.is_symlink():
                                continue

                            if item.is_file():
                                relative = (
                                    Path(source.name) / item.relative_to(source)
                                )
                                files.append((item, relative.as_posix()))

                            elif item.is_dir() and not any(item.iterdir()):
                                relative = (
                                    Path(source.name) / item.relative_to(source)
                                )
                                files.append((None, relative.as_posix() + "/"))

                    else:
                        continue

                    for item, archive_name in files:

                        if item is not None and item.resolve() == output_path.resolve():
                            continue

                        original_name = archive_name
                        counter = 1

                        while archive_name in used_names:
                            archive_name = (
                                f"{counter}_{original_name}"
                            )
                            counter += 1

                        used_names.add(archive_name)

                        if item is None:
                            archive.writestr(archive_name, "")
                        else:
                            archive.write(item, archive_name)

            QMessageBox.information(
                self,
                "ZIP Created",
                f"ZIP archive created successfully:\n{output_path}"
            )

            self.status.setText(f"Created: {output_path.name}")

        except (OSError, zipfile.BadZipFile, RuntimeError) as error:
            QMessageBox.critical(
                self, "ZIP Error", str(error)
            )

    def extract_archive(self, destination):

        archive_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select ZIP File",
            str(Path.home()),
            "ZIP Archives (*.zip)"
        )

        if not archive_path:
            return

        destination = Path(destination)

        try:
            destination.mkdir(parents=True, exist_ok=True)
            destination = destination.resolve()

            with zipfile.ZipFile(archive_path, "r") as archive:

                for member in archive.infolist():
                    target = (destination / member.filename).resolve()

                    if not target.is_relative_to(destination):
                        raise ValueError(
                            "Unsafe ZIP archive: invalid file path detected."
                        )

                archive.extractall(destination)

            QMessageBox.information(
                self,
                "Extraction Complete",
                f"Files extracted successfully to:\n{destination}"
            )

            self.status.setText(
                f"Extracted: {Path(archive_path).name}"
            )

        except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as error:
            QMessageBox.critical(
                self, "Extraction Error", str(error)
            )

    def extract_here(self):

        archive_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select ZIP File",
            str(Path.home()),
            "ZIP Archives (*.zip)"
        )

        if archive_path:
            self.extract_archive_to_parent(archive_path)

    def extract_archive_to_parent(self, archive_path):
        self.extract_archive_from_path(
            archive_path, Path(archive_path).parent
        )

    def extract_to(self):

        archive_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select ZIP File",
            str(Path.home()),
            "ZIP Archives (*.zip)"
        )

        if not archive_path:
            return

        destination = QFileDialog.getExistingDirectory(
            self, "Choose Extraction Location"
        )

        if destination:
            self.extract_archive_from_path(
                archive_path, Path(destination)
            )

    def extract_archive_from_path(self, archive_path, destination):

        destination = Path(destination)

        try:
            destination.mkdir(parents=True, exist_ok=True)
            destination = destination.resolve()

            with zipfile.ZipFile(archive_path, "r") as archive:

                for member in archive.infolist():
                    target = (destination / member.filename).resolve()

                    if not target.is_relative_to(destination):
                        raise ValueError(
                            "Unsafe ZIP archive: invalid file path detected."
                        )

                archive.extractall(destination)

            QMessageBox.information(
                self,
                "Extraction Complete",
                f"Files extracted successfully to:\n{destination}"
            )

            self.status.setText(
                f"Extracted: {Path(archive_path).name}"
            )

        except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as error:
            QMessageBox.critical(
                self, "Extraction Error", str(error)
            )



class PermissionManagerDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Permission Manager")
        self.resize(720, 620)
        self.selected_path = None

        main_layout = QVBoxLayout(self)

        title = QLabel("File & Folder Permission Manager")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        main_layout.addWidget(title)

        path_layout = QHBoxLayout()
        self.path_label = QLabel("No file or folder selected")
        self.path_label.setWordWrap(True)

        select_file = QPushButton("Select File")
        select_folder = QPushButton("Select Folder")

        select_file.clicked.connect(self.select_file)
        select_folder.clicked.connect(self.select_folder)

        path_layout.addWidget(self.path_label, 1)
        path_layout.addWidget(select_file)
        path_layout.addWidget(select_folder)
        main_layout.addLayout(path_layout)

        self.info_label = QLabel("Select a file or folder to view its permissions.")
        self.info_label.setWordWrap(True)
        main_layout.addWidget(self.info_label)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems([
            "Custom",
            "Read Only",
            "Write Only",
            "Read & Write",
            "Read & Execute",
            "Execute Only",
            "No Access",
            "Full Access"
        ])
        self.preset_combo.currentTextChanged.connect(self.apply_preset)

        main_layout.addWidget(QLabel("Permission Preset:"))
        main_layout.addWidget(self.preset_combo)

        permission_box = QGroupBox("Custom Permissions")
        permission_layout = QGridLayout(permission_box)

        permission_layout.addWidget(QLabel("User"), 0, 1)
        permission_layout.addWidget(QLabel("Group"), 0, 2)
        permission_layout.addWidget(QLabel("Others"), 0, 3)

        self.permission_checks = {}

        for row, permission in enumerate(("Read", "Write", "Execute"), start=1):
            permission_layout.addWidget(QLabel(permission), row, 0)

            for column, category in enumerate(("user", "group", "others"), start=1):
                checkbox = QCheckBox()
                checkbox.setChecked(False)
                permission_layout.addWidget(checkbox, row, column)
                self.permission_checks[(category, permission.lower())] = checkbox

        main_layout.addWidget(permission_box)

        self.recursive_check = QCheckBox(
            "Apply recursively to all subfolders and files"
        )
        main_layout.addWidget(self.recursive_check)

        button_layout = QHBoxLayout()

        apply_button = QPushButton("Apply Permissions")
        restore_button = QPushButton("Restore Original Permissions")
        history_button = QPushButton("Permission History")

        apply_button.clicked.connect(self.apply_permissions)
        restore_button.clicked.connect(self.restore_original)
        history_button.clicked.connect(self.show_history)

        button_layout.addWidget(apply_button)
        button_layout.addWidget(restore_button)
        button_layout.addWidget(history_button)

        main_layout.addLayout(button_layout)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        main_layout.addWidget(close_button)

    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if path:
            self.set_selected_path(path)

    def select_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if path:
            self.set_selected_path(path)

    def set_selected_path(self, path):
        self.selected_path = path
        self.path_label.setText(path)
        self.refresh_info()

    def refresh_info(self):
        if not self.selected_path:
            return

        try:
            info = os.lstat(self.selected_path)

            if stat.S_ISLNK(info.st_mode):
                self.info_label.setText("Symbolic links are not supported.")
                return

            owner = pwd.getpwuid(info.st_uid).pw_name
            group = grp.getgrgid(info.st_gid).gr_name
            mode = stat.S_IMODE(info.st_mode)

            self.info_label.setText(
                f"Owner: {owner} | Group: {group}\n"
                f"Permission: {oct(mode)}"
            )

            for (category, permission), checkbox in self.permission_checks.items():
                bit = {
                    ("user", "read"): stat.S_IRUSR,
                    ("user", "write"): stat.S_IWUSR,
                    ("user", "execute"): stat.S_IXUSR,
                    ("group", "read"): stat.S_IRGRP,
                    ("group", "write"): stat.S_IWGRP,
                    ("group", "execute"): stat.S_IXGRP,
                    ("others", "read"): stat.S_IROTH,
                    ("others", "write"): stat.S_IWOTH,
                    ("others", "execute"): stat.S_IXOTH,
                }[(category, permission)]

                checkbox.setChecked(bool(mode & bit))

        except (OSError, KeyError) as error:
            self.info_label.setText(f"Could not read permissions: {error}")

    def apply_preset(self, preset):
        if preset == "Custom":
            return

        settings = {
            "Read Only": (True, False, False),
            "Write Only": (False, True, False),
            "Read & Write": (True, True, False),
            "Read & Execute": (True, False, True),
            "Execute Only": (False, False, True),
            "No Access": (False, False, False),
            "Full Access": (True, True, True),
        }

        read, write, execute = settings[preset]

        for category in ("user", "group", "others"):
            self.permission_checks[(category, "read")].setChecked(read)
            self.permission_checks[(category, "write")].setChecked(write)
            self.permission_checks[(category, "execute")].setChecked(execute)

    def get_selected_items(self):
        path = self.selected_path

        if not path:
            raise ValueError("Please select a file or folder first.")

        root_info = os.lstat(path)

        if stat.S_ISLNK(root_info.st_mode):
            raise ValueError("Symbolic links are not supported.")

        items = [path]

        if self.recursive_check.isChecked() and stat.S_ISDIR(root_info.st_mode):
            for current, directories, files in os.walk(path, followlinks=False):
                directories[:] = [
                    name for name in directories
                    if not os.path.islink(os.path.join(current, name))
                ]

                for name in directories + files:
                    item = os.path.join(current, name)

                    if not os.path.islink(item):
                        items.append(item)

        return items

    def build_permission_mode(self, old_mode):
        mode = stat.S_IMODE(old_mode) & ~0o777

        permission_bits = {
            ("user", "read"): stat.S_IRUSR,
            ("user", "write"): stat.S_IWUSR,
            ("user", "execute"): stat.S_IXUSR,
            ("group", "read"): stat.S_IRGRP,
            ("group", "write"): stat.S_IWGRP,
            ("group", "execute"): stat.S_IXGRP,
            ("others", "read"): stat.S_IROTH,
            ("others", "write"): stat.S_IWOTH,
            ("others", "execute"): stat.S_IXOTH,
        }

        for key, bit in permission_bits.items():
            if self.permission_checks[key].isChecked():
                mode |= bit

        return mode

    def apply_permissions(self):
        try:
            items = self.get_selected_items()
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Permission Error", str(error))
            return

        success = 0
        errors = []

        for path in items:
            try:
                info = os.lstat(path)

                if stat.S_ISLNK(info.st_mode):
                    continue

                old_mode = stat.S_IMODE(info.st_mode)
                new_mode = self.build_permission_mode(info.st_mode)

                owner = pwd.getpwuid(info.st_uid).pw_name
                group = grp.getgrgid(info.st_gid).gr_name

                database.save_original_permission(
                    path,
                    old_mode,
                    info.st_uid,
                    info.st_gid,
                    owner,
                    group,
                    stat.S_ISDIR(info.st_mode)
                )

                os.chmod(path, new_mode, follow_symlinks=False)

                database.save_permission_history(
                    path,
                    old_mode,
                    new_mode,
                    info.st_uid,
                    info.st_uid,
                    info.st_gid,
                    info.st_gid,
                    self.preset_combo.currentText(),
                    self.recursive_check.isChecked(),
                    "SUCCESS"
                )

                success += 1

            except Exception as error:
                errors.append(f"{path}: {error}")

        self.refresh_info()

        message = f"Successfully changed permissions: {success}"

        if errors:
            message += f"\nFailed: {len(errors)}\n\n" + "\n".join(errors[:10])

        QMessageBox.information(self, "Permission Result", message)

    def restore_original(self):
        try:
            items = self.get_selected_items()
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Restore Error", str(error))
            return

        success = 0
        errors = []

        for path in items:
            try:
                record = database.get_original_permission(path)

                if not record:
                    continue

                info = os.lstat(path)

                if stat.S_ISLNK(info.st_mode):
                    continue

                old_mode = stat.S_IMODE(info.st_mode)

                os.chmod(
                    path,
                    record["original_mode"],
                    follow_symlinks=False
                )

                try:
                    os.chown(
                        path,
                        record["original_uid"],
                        record["original_gid"],
                        follow_symlinks=False
                    )
                except PermissionError:
                    errors.append(
                        f"{path}: Permission restored, but owner/group "
                        "could not be restored without administrator rights."
                    )

                database.save_permission_history(
                    path,
                    old_mode,
                    record["original_mode"],
                    info.st_uid,
                    record["original_uid"],
                    info.st_gid,
                    record["original_gid"],
                    "Restore Original",
                    self.recursive_check.isChecked(),
                    "SUCCESS"
                )

                success += 1

            except Exception as error:
                errors.append(f"{path}: {error}")

        self.refresh_info()

        message = f"Original permissions restored: {success}"

        if errors:
            message += "\n\n" + "\n".join(errors[:10])

        QMessageBox.information(self, "Restore Result", message)

    def show_history(self):
        if not self.selected_path:
            QMessageBox.warning(
                self, "Permission History", "Please select a file or folder."
            )
            return

        try:
            records = database.get_permission_history(
                self.selected_path, limit=100
            )

            if not records:
                QMessageBox.information(
                    self, "Permission History", "No permission history found."
                )
                return

            lines = []

            for record in records:
                lines.append(
                    f"Date: {record['changed_at']}\n"
                    f"Type: {record['permission_mode']}\n"
                    f"Old: {oct(record['old_mode'] or 0)} | "
                    f"New: {oct(record['new_mode'] or 0)}\n"
                    f"Status: {record['status']}\n"
                )

            QMessageBox.information(
                self,
                "Permission History",
                "\n".join(lines)
            )

        except Exception as error:
            QMessageBox.warning(
                self, "History Error", str(error)
            )



class PasswordProtectionDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Password Protection")
        self.setMinimumWidth(540)

        layout = QVBoxLayout(self)

        title = QLabel("🔒 Password Protection")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)

        # Protect section
        protect_title = QLabel("Protect File or Folder")
        protect_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(protect_title)

        self.protect_path_input = QLineEdit()
        self.protect_path_input.setReadOnly(True)
        self.protect_path_input.setPlaceholderText("Choose a file or folder...")
        layout.addWidget(self.protect_path_input)

        choose_layout = QHBoxLayout()

        choose_file_btn = QPushButton("Choose File")
        choose_file_btn.clicked.connect(self.choose_file)
        choose_layout.addWidget(choose_file_btn)

        choose_folder_btn = QPushButton("Choose Folder")
        choose_folder_btn.clicked.connect(self.choose_folder)
        choose_layout.addWidget(choose_folder_btn)

        layout.addLayout(choose_layout)

        self.protect_password = QLineEdit()
        self.protect_password.setPlaceholderText("Enter password")
        self.protect_password.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.protect_password)

        self.confirm_password = QLineEdit()
        self.confirm_password.setPlaceholderText("Confirm password")
        self.confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.confirm_password)

        protect_btn = QPushButton("🔒 Protect File / Folder")
        protect_btn.clicked.connect(self.protect_selected)
        layout.addWidget(protect_btn)

        # Separator
        separator = QLabel("────────────────────────────────────")
        layout.addWidget(separator)

        # Unlock section
        unlock_title = QLabel("Unlock Protected File")
        unlock_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(unlock_title)

        self.encrypted_path_input = QLineEdit()
        self.encrypted_path_input.setReadOnly(True)
        self.encrypted_path_input.setPlaceholderText("Choose a protected file...")
        layout.addWidget(self.encrypted_path_input)

        choose_encrypted_btn = QPushButton("Choose Protected File")
        choose_encrypted_btn.clicked.connect(self.choose_encrypted_file)
        layout.addWidget(choose_encrypted_btn)

        self.unlock_password = QLineEdit()
        self.unlock_password.setPlaceholderText("Enter password to unlock")
        self.unlock_password.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.unlock_password)

        unlock_btn = QPushButton("🔓 Unlock File / Folder")
        unlock_btn.clicked.connect(self.unlock_selected)
        layout.addWidget(unlock_btn)

        note = QLabel(
            "Important: If you forget the password, the original content "
            "cannot normally be recovered."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #d99b35;")
        layout.addWidget(note)

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose File to Protect", str(Path.home())
        )
        if path:
            self.protect_path_input.setText(path)

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Choose Folder to Protect", str(Path.home())
        )
        if path:
            self.protect_path_input.setText(path)

    def choose_encrypted_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Protected File",
            str(Path.home()),
            "All Files (*)"
        )
        if path:
            self.encrypted_path_input.setText(path)

    def protect_selected(self):
        path = self.protect_path_input.text().strip()
        password = self.protect_password.text()
        confirm = self.confirm_password.text()

        if not path:
            QMessageBox.warning(self, "Select File or Folder",
                                "Please choose a file or folder first.")
            return

        if not password:
            QMessageBox.warning(self, "Password Required",
                                "Please enter a password.")
            return

        if password != confirm:
            QMessageBox.warning(self, "Password Mismatch",
                                "The passwords do not match.")
            return

        try:
            result = password_manager.protect_path(path, password)

            if result.get("success"):
                QMessageBox.information(
                    self, "Protection Successful",
                    result.get("message", "Protected successfully.")
                )
                self.protect_path_input.clear()
            else:
                QMessageBox.warning(
                    self, "Protection Warning",
                    result.get("message", "Protection was not fully completed.")
                )

        except Exception as error:
            QMessageBox.critical(self, "Protection Error", str(error))

        finally:
            self.protect_password.clear()
            self.confirm_password.clear()

    def unlock_selected(self):
        path = self.encrypted_path_input.text().strip()
        password = self.unlock_password.text()

        if not path:
            QMessageBox.warning(self, "Select Protected File",
                                "Please choose a protected file first.")
            return

        if not password:
            QMessageBox.warning(self, "Password Required",
                                "Please enter the password.")
            return

        try:
            result = password_manager.unlock_file(path, password)

            if result.get("success"):
                QMessageBox.information(
                    self, "Unlock Successful",
                    result.get("message", "Unlocked successfully.")
                )
                self.encrypted_path_input.clear()
            else:
                QMessageBox.warning(
                    self, "Unlock Failed",
                    result.get("message", "Could not unlock the file.")
                )

        except Exception as error:
            QMessageBox.critical(
                self, "Unlock Error",
                "Could not unlock the encrypted file.\n\n" + str(error)
            )

        finally:
            self.unlock_password.clear()


# =========================================================
# MAIN FILE MANAGER
# =========================================================


class FileManager(QWidget):

    def __init__(self):
        super().__init__()

        self.current_folder = Path.home()
        self.dark_mode = True
        self.all_items = []
        self.history_dialog = None

        self.search_worker = None
        self.search_workers = set()
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(500)
        self.search_timer.timeout.connect(self.start_global_search)
        self.search_result_paths = set()

        self.setWindowTitle("Smart File Manager")
        self.resize(1200, 760)
        self.setMinimumSize(700, 450)

        self.build_ui()
        self.apply_theme()
        self.load_files()

    # =====================================================
    # BUILD UI
    # =====================================================

    def build_ui(self):

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        # Header
        header = QHBoxLayout()

        brand_icon = QLabel("✦")
        brand_icon.setObjectName("BrandIcon")
        brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_icon.setFixedSize(52, 52)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(3)

        title = QLabel("Smart File Manager")
        title.setObjectName("MainTitle")
        title.setWordWrap(True)
        title.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred
        )

        subtitle = QLabel(
            "Organize your files. Keep everything in order."
        )
        subtitle.setObjectName("Subtitle")
        subtitle.setWordWrap(True)

        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)

        brand_layout = QHBoxLayout()
        brand_layout.setSpacing(14)
        brand_layout.addWidget(brand_icon)
        brand_layout.addLayout(title_layout)

        header.addLayout(brand_layout)
        header.addStretch()

        self.theme_button = QPushButton("☀  Light Mode")
        self.theme_button.clicked.connect(self.toggle_theme)
        self.theme_button.setObjectName("ThemeButton")
        self.theme_button.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed
        )

        header.addWidget(self.theme_button)
        root_layout.addLayout(header)

        # Navigation toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.back_button = QPushButton("←  Up")
        self.back_button.clicked.connect(self.go_up)

        self.home_button = QPushButton("⌂  Home")
        self.home_button.clicked.connect(self.go_home)

        self.refresh_button = QPushButton("⟳  Refresh")
        self.refresh_button.clicked.connect(self.load_files)

        self.history_button = QPushButton("◷  History")
        self.history_button.clicked.connect(self.show_history)

        toolbar.addWidget(self.back_button)
        toolbar.addWidget(self.home_button)
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.history_button)
        toolbar.addStretch()

        root_layout.addLayout(toolbar)

        # Current location
        self.path_label = QLabel()
        self.path_label.setObjectName("PathLabel")
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.path_label.setWordWrap(False)
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        root_layout.addWidget(self.path_label)
        self.path_label.setToolTip("")

        # Dashboard summary cards
        dashboard_layout = QHBoxLayout()
        dashboard_layout.setSpacing(12)

        self.dashboard_labels = {}

        dashboard_cards = [
            ("files", "TOTAL FILES", "📄", "Files in this folder"),
            ("folders", "FOLDERS", "📁", "Folders in this location"),
            ("storage", "STORAGE USED", "💾", "Size of files in this folder"),
            ("location", "CURRENT LOCATION", "📍", "Active folder"),
        ]

        for key, heading, icon, hint in dashboard_cards:
            card = QFrame()
            card.setObjectName("DashboardCard")
            card.setProperty("cardType", key)
            card.setMinimumHeight(116)

            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            card_layout.setSpacing(13)

            icon_badge = QLabel(icon)
            icon_badge.setObjectName("DashboardIcon")
            icon_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_badge.setFixedSize(48, 48)

            info_layout = QVBoxLayout()
            info_layout.setSpacing(4)

            title_label = QLabel(heading)
            title_label.setObjectName("DashboardTitle")

            value_label = QLabel("--")
            value_label.setObjectName("DashboardValue")
            value_label.setWordWrap(True)

            hint_label = QLabel(hint)
            hint_label.setObjectName("DashboardHint")
            hint_label.setWordWrap(True)

            info_layout.addWidget(title_label)
            info_layout.addWidget(value_label)
            info_layout.addWidget(hint_label)

            card_layout.addWidget(icon_badge)
            card_layout.addLayout(info_layout, 1)

            self.dashboard_labels[key] = value_label
            dashboard_layout.addWidget(card, 1)

        root_layout.addLayout(dashboard_layout)

        # Main horizontal area
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Sidebar with vertical scrolling
        sidebar = QFrame()
        self.sidebar = sidebar
        sidebar.setObjectName("Sidebar")
        sidebar.setMinimumWidth(160)
        sidebar.setMaximumWidth(240)

        sidebar_outer_layout = QVBoxLayout(sidebar)
        sidebar_outer_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_outer_layout.setSpacing(0)

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sidebar_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        sidebar_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        sidebar_content = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_content)
        sidebar_layout.setContentsMargins(10, 14, 10, 14)
        sidebar_layout.setSpacing(8)

        sidebar_scroll.setWidget(sidebar_content)
        sidebar_outer_layout.addWidget(sidebar_scroll)

        sidebar_title = QLabel("  NAVIGATION")
        sidebar_title.setObjectName("SectionLabel")
        sidebar_layout.addWidget(sidebar_title)

        locations = [
            ("⌂   Home", Path.home()),
            ("▣   Desktop", Path.home() / "Desktop"),
            ("▤   Documents", Path.home() / "Documents"),
            ("⇩   Downloads", Path.home() / "Downloads"),
            ("▧   Pictures", Path.home() / "Pictures"),
            ("♫   Music", Path.home() / "Music"),
            ("▶   Videos", Path.home() / "Videos"),
        ]

        self.sidebar_buttons = []

        for label, folder in locations:
            button = QPushButton(label)
            button.setObjectName("SidebarButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)

            button.clicked.connect(
                lambda checked=False, p=folder:
                self.navigate_to(p)
            )

            sidebar_layout.addWidget(button)
            self.sidebar_buttons.append(button)

        sidebar_tools_title = QLabel("  TOOLS")
        sidebar_tools_title.setObjectName("SectionLabel")
        sidebar_layout.addSpacing(14)
        sidebar_layout.addWidget(sidebar_tools_title)

        sidebar_empty_cleaner = QPushButton("▱   Empty Folder Cleaner")
        sidebar_empty_cleaner.setObjectName("SidebarButton")
        sidebar_empty_cleaner.clicked.connect(
            self.show_empty_folder_cleaner
        )
        sidebar_layout.addWidget(sidebar_empty_cleaner)

        sidebar_large_files = QPushButton("▤   Large File Finder")
        sidebar_large_files.setObjectName("SidebarButton")
        sidebar_large_files.clicked.connect(
            self.show_large_file_finder
        )
        sidebar_layout.addWidget(sidebar_large_files)

        sidebar_duplicate = QPushButton("▦   Duplicate File Finder")
        sidebar_duplicate.setObjectName("SidebarButton")
        sidebar_duplicate.clicked.connect(
            self.show_duplicate_file_finder
        )
        sidebar_layout.addWidget(sidebar_duplicate)

        sidebar_archive = QPushButton("▣   ZIP & UNZIP Manager")
        sidebar_archive.setObjectName("SidebarButton")
        sidebar_archive.clicked.connect(self.show_archive_manager)
        sidebar_layout.addWidget(sidebar_archive)

        sidebar_permission = QPushButton("🔐   Permission Manager")
        sidebar_permission.setObjectName("SidebarButton")
        sidebar_permission.clicked.connect(self.show_permission_manager)
        sidebar_layout.addWidget(sidebar_permission)

        sidebar_password = QPushButton("🔒   Password Protection")
        sidebar_password.setObjectName("SidebarButton")
        sidebar_password.clicked.connect(self.show_password_protection)
        sidebar_layout.addWidget(sidebar_password)

        sidebar_layout.addStretch()

        sidebar_history = QPushButton("◷   Arrangement History")
        sidebar_history.setObjectName("SidebarButton")
        sidebar_history.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )
        sidebar_history.clicked.connect(self.show_history)
        sidebar_layout.addWidget(sidebar_history)

        self.sidebar_buttons.extend([
            sidebar_empty_cleaner,
            sidebar_large_files,
            sidebar_duplicate,
            sidebar_archive,
            sidebar_permission,
            sidebar_password,
            sidebar_history
        ])

        for button in self.sidebar_buttons:
            button.setMinimumWidth(0)
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed
            )

        splitter.addWidget(sidebar)

        # Center content
        center = QFrame()
        center.setObjectName("ContentPanel")

        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(14, 14, 14, 14)
        center_layout.setSpacing(12)

        # Search
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(
            "  🔍  Search files and folders..."
        )
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self.filter_files)

        center_layout.addWidget(self.search_box)

        # Professional File Explorer Heading
        explorer_header = QHBoxLayout()
        explorer_header.setSpacing(10)

        explorer_title = QLabel("File Explorer")
        explorer_title.setObjectName("ExplorerTitle")

        self.file_count_label = QLabel("Files and folders")
        self.file_count_label.setObjectName("FileCountBadge")

        explorer_header.addWidget(explorer_title)
        explorer_header.addStretch()
        explorer_header.addWidget(self.file_count_label)

        center_layout.addLayout(explorer_header)

        # File list
        self.file_list = QListWidget()
        self.file_list.setObjectName("FileList")

        self.file_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )

        self.file_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )

        self.file_list.currentItemChanged.connect(
            self.show_details
        )

        self.file_list.itemDoubleClicked.connect(
            self.open_item
        )

        self.file_list.customContextMenuRequested.connect(
            self.show_context_menu
        )

        center_layout.addWidget(self.file_list, 1)

        splitter.addWidget(center)

        # Details panel
        details_panel = QFrame()
        details_panel.setObjectName("DetailsPanel")
        details_panel.setMinimumWidth(240)
        details_panel.setMaximumWidth(360)

        details_layout = QVBoxLayout(details_panel)
        details_layout.setContentsMargins(14, 14, 14, 14)
        details_layout.setSpacing(10)

        details_title = QLabel("File Details")
        details_title.setObjectName("PanelTitle")

        details_subtitle = QLabel(
            "Select a file or folder to see its information."
        )
        details_subtitle.setObjectName("Subtitle")
        details_subtitle.setWordWrap(True)

        # Professional Details Panel Heading
        details_header = QHBoxLayout()
        details_header.setSpacing(10)

        details_icon = QLabel("▤")
        details_icon.setObjectName("DetailsIcon")
        details_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        details_icon.setFixedSize(38, 38)

        details_header.addWidget(details_icon)
        details_header.addWidget(details_title, 1)

        details_layout.addLayout(details_header)
        details_layout.addWidget(details_subtitle)

        self.details = QLabel("No item selected")
        self.details.setObjectName("DetailsText")
        self.details.setWordWrap(True)
        self.details.setTextFormat(
            Qt.TextFormat.RichText
        )
        self.details.setAlignment(
            Qt.AlignmentFlag.AlignTop
        )
        self.details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.details.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred
        )

        details_scroll = QScrollArea()
        details_scroll.setWidgetResizable(True)
        details_scroll.setFrameShape(
            QFrame.Shape.NoFrame
        )
        details_scroll.setWidget(self.details)

        details_layout.addWidget(details_scroll, 1)

        splitter.addWidget(details_panel)

        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([205, 680, 315])

        root_layout.addWidget(splitter, 1)
        splitter.splitterMoved.connect(
            self.update_sidebar_button_fonts
        )

        self.update_sidebar_button_fonts()

        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("StatusLabel")

        root_layout.addWidget(self.status_label)

    # =====================================================
    # RESPONSIVE SIDEBAR
    # =====================================================

    def update_sidebar_button_fonts(self):
        if not hasattr(self, "sidebar_buttons"):
            return

        for button in self.sidebar_buttons:
            available_width = button.width() - 28

            if available_width <= 0:
                continue

            font_size = 10.0

            while font_size > 6.0:
                font = QFont("Ubuntu")
                font.setPointSizeF(font_size)

                metrics = QFontMetricsF(font)

                if metrics.horizontalAdvance(button.text()) <= available_width:
                    break

                font_size -= 0.5

            button.setStyleSheet(
                f"font-size: {font_size:.1f}pt;"
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_sidebar_button_fonts()

    # =====================================================
    # THEMES
    # =====================================================

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.apply_theme()

    def apply_theme(self):

        if self.dark_mode:
            self.setStyleSheet("""
                QWidget {
                    background-color: #0B1020;
                    color: #E2E8F0;
                    font-family: "Ubuntu";
                    font-size: 10pt;
                }

                #MainTitle {
                    font-size: 25pt;
                    font-weight: bold;
                    color: #F8FAFF;
                }

                #Subtitle {
                    color: #94A3B8;
                    font-size: 9pt;
                }

                #SectionLabel {
                    color: #60A5FA;
                    font-size: 9pt;
                    font-weight: bold;
                }

                #PanelTitle {
                    color: #F8FAFF;
                    font-size: 16pt;
                    font-weight: bold;
                }

                #Sidebar, #DetailsPanel, #ContentPanel {
                    background-color: #111A2E;
                    border: 1px solid #263653;
                    border-radius: 16px;
                }

                QFrame#DashboardCard {
                    border-radius: 14px;
                    border: 1px solid #334155;
                }

                QFrame#DashboardCard[cardType="files"] {
                    background-color: #142F59;
                    border: 1px solid #3B82F6;
                }

                QFrame#DashboardCard[cardType="folders"] {
                    background-color: #302052;
                    border: 1px solid #A78BFA;
                }

                QFrame#DashboardCard[cardType="storage"] {
                    background-color: #123C35;
                    border: 1px solid #34D399;
                }

                QFrame#DashboardCard[cardType="location"] {
                    background-color: #123B49;
                    border: 1px solid #2DD4BF;
                }

                QLabel#BrandIcon {
                    background-color: #172D55;
                    color: #60A5FA;
                    border: 1px solid #3B82F6;
                    border-radius: 15px;
                    font-size: 25pt;
                    font-weight: bold;
                }

                QLabel#DashboardIcon {
                    background-color: rgba(255, 255, 255, 0.10);
                    border: 1px solid rgba(255, 255, 255, 0.22);
                    border-radius: 13px;
                    font-size: 21pt;
                }

                QLabel#DashboardTitle {
                    color: #CBD5E1;
                    font-size: 8pt;
                    font-weight: bold;
                }

                QLabel#DashboardValue {
                    color: #FFFFFF;
                    font-size: 22pt;
                    font-weight: bold;
                }

                QLabel#DashboardHint {
                    color: #A5B4C8;
                    font-size: 8pt;
                }

                QPushButton {
                    background-color: #1D2A43;
                    color: #E2E8F0;
                    border: 1px solid #334766;
                    border-radius: 10px;
                    padding: 10px 14px;
                }

                QPushButton:hover {
                    background-color: #293D60;
                    border: 1px solid #3B82F6;
                }

                QPushButton:pressed {
                    background-color: #2563EB;
                }

                #SidebarButton {
                    text-align: left;
                    padding: 12px 10px;
                    background-color: transparent;
                    border: 1px solid transparent;
                    border-radius: 10px;
                    color: #B8C5D9;
                }

                #SidebarButton:hover {
                    background-color: #1E3152;
                    color: #FFFFFF;
                    border: 1px solid #34517C;
                }

                #ThemeButton {
                    background-color: #2563EB;
                    color: white;
                    font-weight: bold;
                    padding: 11px 16px;
                    border: 1px solid #60A5FA;
                    border-radius: 11px;
                }

                #ThemeButton:hover {
                    background-color: #3B82F6;
                }

                QLineEdit {
                    background-color: #0D172A;
                    color: #F8FAFC;
                    border: 1px solid #334766;
                    border-radius: 11px;
                    padding: 12px;
                    selection-background-color: #2563EB;
                }

                QLineEdit:focus {
                    border: 1px solid #60A5FA;
                    background-color: #111F36;
                }

                QListWidget {
                    background-color: #0D172A;
                    color: #E2E8F0;
                    border: 1px solid #263653;
                    border-radius: 12px;
                    padding: 8px;
                    outline: none;
                }

                QListWidget::item {
                    padding: 12px;
                    border-radius: 8px;
                }

                QListWidget::item:hover {
                    background-color: #1B2C49;
                }

                QListWidget::item:selected {
                    background-color: #1D4ED8;
                    color: white;
                    border: 1px solid #60A5FA;
                }

                #PathLabel {
                    background-color: #14233D;
                    border: 1px solid #2D456B;
                    border-radius: 10px;
                    padding: 11px;
                    color: #93C5FD;
                }

                #DetailsText {
                    color: #DCE6F5;
                    background-color: #111A2E;
                    padding: 6px;
                }

                #StatusLabel {
                    color: #94A3B8;
                    padding: 5px;
                }

                QScrollArea {
                    background-color: transparent;
                    border: none;
                }

                QScrollBar:vertical {
                    background-color: #111A2E;
                    width: 9px;
                    margin: 3px;
                    border-radius: 4px;
                }

                QScrollBar::handle:vertical {
                    background-color: #405778;
                    min-height: 25px;
                    border-radius: 4px;
                }

                QScrollBar::handle:vertical:hover {
                    background-color: #60A5FA;
                }

                QScrollBar::add-line:vertical,
                QScrollBar::sub-line:vertical {
                    height: 0px;
                }

                QTableWidget {
                    background-color: #0D172A;
                    alternate-background-color: #14213A;
                    color: #E2E8F0;
                    gridline-color: #263653;
                    border: 1px solid #263653;
                    border-radius: 10px;
                    selection-background-color: #1D4ED8;
                }

                QHeaderView::section {
                    background-color: #1B2B47;
                    color: #BFDBFE;
                    padding: 10px;
                    border: none;
                    font-weight: bold;
                }

                QCheckBox {
                    color: #DCE6F5;
                    spacing: 8px;
                }

                QGroupBox {
                    background-color: #111A2E;
                    border: 1px solid #263653;
                    border-radius: 12px;
                    margin-top: 12px;
                    padding: 12px;
                    font-weight: bold;
                    color: #E2E8F0;
                }

                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 5px;
                    color: #60A5FA;
                }

                QProgressBar {
                    background-color: #263653;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    text-align: center;
                    min-height: 12px;
                }

                QProgressBar::chunk {
                    background-color: #3B82F6;
                    border-radius: 6px;
                }

                QMenu {
                    background-color: #17233A;
                    color: #E2E8F0;
                    border: 1px solid #334766;
                    padding: 5px;
                }

                QMenu::item {
                    padding: 8px 25px;
                    border-radius: 5px;
                }

                QMenu::item:selected {
                    background-color: #263F68;
                    color: white;
                }

                QToolTip {
                    background-color: #1E293B;
                    color: #FFFFFF;
                    border: 1px solid #60A5FA;
                    padding: 6px;
                }

                QSplitter::handle {
                    background-color: #263653;
                    width: 6px;
                    border-radius: 3px;
                }

                QSplitter::handle:hover {
                    background-color: #3B82F6;
                }
            """)

            self.theme_button.setText("☀  Light Mode")

        else:
            self.setStyleSheet("""
                QWidget {
                    background-color: #F3F6FC;
                    color: #263650;
                    font-family: "Ubuntu";
                    font-size: 10pt;
                }

                #MainTitle {
                    color: #172B55;
                    font-size: 24pt;
                    font-weight: 800;
                }

                #Subtitle { color: #7B89A4; font-size: 9pt; }

                #BrandIcon {
                    background-color: #E7EDFF;
                    color: #5267E8;
                    border: 1px solid #D6E0FF;
                    border-radius: 15px;
                    font-size: 25pt;
                    font-weight: bold;
                }

                #SectionLabel {
                    color: #6676A0;
                    font-size: 8pt;
                    font-weight: bold;
                }

                #PanelTitle {
                    color: #1D3158;
                    font-size: 16pt;
                    font-weight: 800;
                }

                #Sidebar, #DetailsPanel, #ContentPanel {
                    background-color: #FFFFFF;
                    border: 1px solid #E1E8F4;
                    border-radius: 16px;
                }

                #Sidebar { background-color: #FBFCFF; }
                #DetailsPanel { background-color: #FCFDFF; }

                QFrame#DashboardCard {
                    border-radius: 15px;
                    border: 1px solid #E1E8F4;
                }

                QFrame#DashboardCard[cardType="files"] {
                    background-color: #EDF3FF;
                    border: 1px solid #D5E3FF;
                }

                QFrame#DashboardCard[cardType="folders"] {
                    background-color: #F4F0FF;
                    border: 1px solid #E3D9FF;
                }

                QFrame#DashboardCard[cardType="storage"] {
                    background-color: #ECF9F2;
                    border: 1px solid #CFEFDE;
                }

                QFrame#DashboardCard[cardType="location"] {
                    background-color: #ECF8FC;
                    border: 1px solid #CDEBF3;
                }

                QLabel#DashboardIcon {
                    background-color: rgba(255,255,255,190);
                    border: 1px solid rgba(255,255,255,230);
                    border-radius: 13px;
                    font-size: 21pt;
                }

                QLabel#DashboardTitle {
                    color: #71809B;
                    font-size: 8pt;
                    font-weight: bold;
                }

                QLabel#DashboardValue {
                    color: #1E2D49;
                    font-size: 20pt;
                    font-weight: 800;
                }

                QLabel#DashboardHint {
                    color: #8492AA;
                    font-size: 8pt;
                }

                QFrame#DashboardCard[cardType="files"] QLabel#DashboardValue {
                    color: #3266D5;
                }
                QFrame#DashboardCard[cardType="folders"] QLabel#DashboardValue {
                    color: #7950CE;
                }
                QFrame#DashboardCard[cardType="storage"] QLabel#DashboardValue {
                    color: #16865D;
                }
                QFrame#DashboardCard[cardType="location"] QLabel#DashboardValue {
                    color: #147B91;
                }

                QPushButton {
                    background-color: #F0F4FB;
                    color: #42516D;
                    border: 1px solid #E1E8F3;
                    border-radius: 9px;
                    padding: 9px 13px;
                    font-weight: 600;
                }

                QPushButton:hover {
                    background-color: #E7EEFF;
                    color: #354FB0;
                    border: 1px solid #C9D7FF;
                }

                QPushButton:pressed { background-color: #DCE6FF; }

                #ThemeButton {
                    background-color: #4F5FE5;
                    color: white;
                    border: 1px solid #4F5FE5;
                    border-radius: 10px;
                    padding: 11px 17px;
                    font-weight: bold;
                }

                #ThemeButton:hover { background-color: #4050D0; }

                #SidebarButton {
                    background-color: transparent;
                    color: #586781;
                    border: 1px solid transparent;
                    border-radius: 9px;
                    text-align: left;
                    padding: 11px 10px;
                    font-weight: 600;
                }

                #SidebarButton:hover {
                    background-color: #EEF3FF;
                    color: #3E55B7;
                    border-color: #E1E9FF;
                }

                #SidebarButton:pressed { background-color: #E2E9FF; }

                QLineEdit, QComboBox {
                    background-color: white;
                    color: #253550;
                    border: 1px solid #D9E2F0;
                    border-radius: 10px;
                    padding: 11px 12px;
                    selection-background-color: #DCE5FF;
                    selection-color: #263F99;
                }

                QLineEdit:hover, QComboBox:hover { border-color: #B9C9ED; }

                QLineEdit:focus, QComboBox:focus {
                    border: 1px solid #7185E8;
                }

                QListWidget#FileList {
                    background-color: white;
                    color: #33435F;
                    border: 1px solid #E3EAF4;
                    border-radius: 11px;
                    padding: 7px;
                    outline: none;
                }

                QListWidget#FileList::item {
                    padding: 11px 10px;
                    border-radius: 8px;
                }

                QListWidget#FileList::item:hover {
                    background-color: #F2F5FF;
                    color: #354FAE;
                }

                QListWidget#FileList::item:selected {
                    background-color: #E7EDFF;
                    color: #304AA8;
                    border: 1px solid #D6E0FF;
                }

                #PathLabel {
                    background-color: #EEF2FF;
                    border: 1px solid #DDE5FF;
                    border-radius: 9px;
                    padding: 10px 13px;
                    color: #4558B8;
                    font-weight: 600;
                }

                QLabel#ExplorerTitle {
                    color: #1D3158;
                    font-size: 15pt;
                    font-weight: 800;
                    padding: 3px 0;
                }

                QLabel#FileCountBadge {
                    background-color: #EEF2FF;
                    color: #4B5FC1;
                    border: 1px solid #DDE5FF;
                    border-radius: 9px;
                    padding: 6px 11px;
                    font-size: 8pt;
                    font-weight: bold;
                }

                QLabel#DetailsIcon {
                    background-color: #EAF0FF;
                    color: #5267D8;
                    border: 1px solid #DCE5FF;
                    border-radius: 11px;
                    font-size: 19pt;
                    font-weight: bold;
                }

                #DetailsText {
                    color: #42516A;
                    background-color: #FCFDFF;
                    padding: 6px;
                }

                #StatusLabel {
                    color: #7B89A2;
                    padding: 5px 3px;
                }

                QScrollArea { background-color: transparent; border: none; }

                QScrollBar:vertical {
                    background-color: #F2F5FA;
                    width: 9px;
                    margin: 3px;
                    border-radius: 4px;
                }

                QScrollBar::handle:vertical {
                    background-color: #C3CEE0;
                    min-height: 25px;
                    border-radius: 4px;
                }

                QScrollBar::handle:vertical:hover {
                    background-color: #91A5C8;
                }

                QScrollBar::add-line:vertical,
                QScrollBar::sub-line:vertical { height: 0px; }

                QTableWidget {
                    background-color: white;
                    alternate-background-color: #F7F9FD;
                    color: #33435F;
                    gridline-color: #E9EEF5;
                    border: 1px solid #E1E8F2;
                    border-radius: 10px;
                    selection-background-color: #E7EDFF;
                    selection-color: #304AA8;
                }

                QHeaderView::section {
                    background-color: #F0F4FC;
                    color: #52617D;
                    padding: 10px;
                    border: none;
                    border-bottom: 1px solid #E1E8F2;
                    font-weight: bold;
                }

                QCheckBox { color: #42516A; spacing: 8px; }

                QGroupBox {
                    background-color: white;
                    border: 1px solid #E1E8F2;
                    border-radius: 11px;
                    margin-top: 12px;
                    padding: 12px;
                    font-weight: bold;
                    color: #35445F;
                }

                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 5px;
                    color: #5264C8;
                }

                QProgressBar {
                    background-color: #E9EEF7;
                    color: #34435D;
                    border: none;
                    border-radius: 6px;
                    text-align: center;
                    min-height: 12px;
                }

                QProgressBar::chunk {
                    background-color: #6477E8;
                    border-radius: 6px;
                }

                QMenu {
                    background-color: white;
                    color: #34435D;
                    border: 1px solid #E1E8F2;
                    padding: 5px;
                }

                QMenu::item { padding: 8px 25px; border-radius: 5px; }
                QMenu::item:selected {
                    background-color: #EEF2FF;
                    color: #354BA8;
                }

                QToolTip {
                    background-color: #263653;
                    color: white;
                    border: 1px solid #405477;
                    padding: 6px;
                }

                QSplitter::handle {
                    background-color: #E7ECF5;
                    width: 5px;
                    border-radius: 2px;
                }

                QSplitter::handle:hover { background-color: #9BAAE9; }
            """)

            self.theme_button.setText("🌙  Dark Mode")

    # =====================================================
    # DASHBOARD
    # =====================================================

    def update_dashboard_cards(self, items):

        files = 0
        folders = 0
        total_size = 0

        for path in items:
            try:
                if path.is_dir():
                    folders += 1
                elif path.is_file():
                    files += 1
                    total_size += path.stat().st_size
            except OSError:
                continue

        if total_size < 1024:
            size_text = f"{total_size} B"
        elif total_size < 1024 ** 2:
            size_text = f"{total_size / 1024:.1f} KB"
        elif total_size < 1024 ** 3:
            size_text = f"{total_size / (1024 ** 2):.1f} MB"
        else:
            size_text = f"{total_size / (1024 ** 3):.2f} GB"

        self.dashboard_labels["files"].setText(str(files))
        self.dashboard_labels["folders"].setText(str(folders))
        self.dashboard_labels["storage"].setText(size_text)

        location_name = self.current_folder.name or str(self.current_folder)
        self.dashboard_labels["location"].setText(location_name)
        self.dashboard_labels["location"].setToolTip(str(self.current_folder))

    # =====================================================
    # LOAD FILES
    # =====================================================

    def load_files(self):

        self.file_list.clear()
        self.all_items = []

        self.path_label.setText(
            f"Location:  {self.current_folder}"
        )

        try:
            items = sorted(
                self.current_folder.iterdir(),
                key=lambda item: (
                    not item.is_dir(),
                    item.name.lower()
                )
            )

        except (PermissionError, OSError) as error:
            QMessageBox.warning(
                self,
                "Folder Error",
                str(error)
            )
            return

        for path in items:
            self.all_items.append(path)

        self.update_dashboard_cards(items)

        self.filter_files(self.search_box.text())

        self.details.setText(
            "<h3>Welcome!</h3>"
            "<p>Select a file or folder to see its details.</p>"
            "<p>Double-click a folder to open it.</p>"
            "<p>Right-click selected files to arrange them.</p>"
        )

        self.status_label.setText(
            f"Loaded {len(items)} item(s)"
        )

    # =====================================================
    # SEARCH
    # =====================================================

    def filter_files(self, text=""):

        if not hasattr(self, "file_list"):
            return

        query = text.strip()

        if query:
            self.search_timer.stop()
            self.cancel_global_search()

            self.file_list.clear()
            self.search_result_paths = set()
            self.file_count_label.setText("GLOBAL SEARCH")
            self.status_label.setText("Preparing global search...")
            self.search_timer.start()
            return

        self.search_timer.stop()
        self.cancel_global_search()

        self.file_list.clear()
        visible_count = 0

        for path in self.all_items:
            icon = "📁" if path.is_dir() else "📄"
            item = QListWidgetItem(f"{icon}   {path.name}")
            item.setData(
                Qt.ItemDataRole.UserRole,
                str(path.resolve())
            )
            item.setToolTip(str(path))
            self.file_list.addItem(item)
            visible_count += 1

        self.file_count_label.setText(
            f"FILES & FOLDERS  ·  {visible_count}"
        )

        self.status_label.setText(
            f"Loaded {len(self.all_items)} item(s)"
        )

    def cancel_global_search(self):

        worker = self.search_worker
        self.search_worker = None

        if worker is not None:
            try:
                if worker.isRunning():
                    worker.requestInterruption()
            except RuntimeError:
                pass

    def start_global_search(self):

        query = self.search_box.text().strip()
        if not query:
            return

        self.cancel_global_search()

        self.file_list.clear()
        self.search_result_paths = set()

        worker = GlobalSearchWorker(query, self)
        self.search_worker = worker
        self.search_workers.add(worker)

        worker.result_found.connect(
            lambda path, current_worker=worker:
                self.add_search_result(path)
                if self.search_worker is current_worker else None
        )

        worker.search_finished.connect(
            lambda count, current_worker=worker:
                self.global_search_finished(count)
                if self.search_worker is current_worker else None
        )

        worker.finished.connect(self.cleanup_search_worker)

        self.status_label.setText(
            f"Searching the computer for: {query}"
        )

        worker.start()

    def cleanup_search_worker(self):

        worker = self.sender()

        if worker is None:
            return

        if self.search_worker is worker:
            self.search_worker = None

        self.search_workers.discard(worker)
        worker.deleteLater()

    def add_search_result(self, path_text):

        if self.search_box.text().strip() == "":
            return

        if path_text in self.search_result_paths:
            return

        self.search_result_paths.add(path_text)
        path = Path(path_text)

        icon = "📁" if path.is_dir() else "📄"
        item = QListWidgetItem(f"{icon}   {path.name}")

        item.setData(
            Qt.ItemDataRole.UserRole,
            path_text
        )
        item.setToolTip(path_text)

        self.file_list.addItem(item)

        self.file_count_label.setText(
            f"GLOBAL SEARCH  ·  {len(self.search_result_paths)}"
        )

    def global_search_finished(self, count):

        if self.search_box.text().strip():
            self.status_label.setText(
                f"Search completed. Found {count} item(s)."
            )


    # =====================================================
    # FILE DETAILS
    # =====================================================

    def show_details(self, current_item, previous_item=None):

        if current_item is None:
            self.details.setText("No item selected.")
            return

        stored_path = current_item.data(
            Qt.ItemDataRole.UserRole
        )

        if not stored_path:
            self.details.setText("Path is not available.")
            return

        path = Path(stored_path)

        try:
            if not path.exists():
                self.details.setText(
                    "This file or folder no longer exists."
                )
                return

            if path.is_dir():

                items = sorted(
                    path.iterdir(),
                    key=lambda p: (
                        not p.is_dir(),
                        p.name.lower()
                    )
                )

                lines = [
                    "<h3>📁 Folder Information</h3>",
                    f"<b>Name:</b> {safe_html(path.name)}<br>",
                    f"<b>Location:</b> {safe_html(path.resolve())}<br>",
                    f"<b>Direct items:</b> {len(items)}<br>",
                    "<hr><h3>Contents</h3>",
                ]

                if not items:
                    lines.append("This folder is empty.")

                for index, item in enumerate(items, start=1):

                    if item.is_dir():
                        lines.append(
                            f"<b>{index}. 📁 "
                            f"{safe_html(item.name)}</b><br>"
                            "<i>Subfolder contents not shown.</i><br><br>"
                        )
                        continue

                    try:
                        stat = item.stat()
                        saved = get_database_details(item)

                        category = get_category(item)
                        original = "Not recorded"
                        arrange_time = "Not arranged yet"

                        if saved:
                            category = (
                                saved["category"] or category
                            )
                            original = (
                                saved["original_location"]
                                or original
                            )
                            arrange_time = (
                                saved["arrange_time"]
                                or arrange_time
                            )

                        lines.append(
                            f"<b>{index}. {safe_html(item.name)}</b><br>"
                            f"Type: {safe_html(item.suffix.upper() or 'File')}<br>"
                            f"Size: {get_size(stat.st_size)}<br>"
                            f"Category: {safe_html(category)}<br>"
                            f"Original: {safe_html(original)}<br>"
                            f"Modified: {format_time(stat.st_mtime)}<br>"
                            f"Arrange time: {safe_html(arrange_time)}<br><br>"
                        )

                    except (OSError, sqlite3.Error, TypeError, ValueError):
                        lines.append(
                            f"{index}. {safe_html(item.name)}"
                            " — Details unavailable.<br><br>"
                        )

                self.details.setText("".join(lines))
                return

            # Selected file
            stat = path.stat()
            saved = get_database_details(path)
            arrange_record = database.get_file_arrange_type(
                str(path.resolve())
            )

            arrange_type = (
                arrange_record["arrange_type"]
                if arrange_record and arrange_record["arrange_type"]
                else "Not arranged yet"
            )

            category = get_category(path)
            original = "Not recorded"
            arrange_time = "Not arranged yet"

            if saved:
                category = saved["category"] or category
                original = (
                    saved["original_location"] or original
                )
                arrange_time = (
                    saved["arrange_time"] or arrange_time
                )

            file_type = path.suffix.upper() or "File"

            info = f"""
                <h3>📄 File Information</h3>
                <hr>
                <b>Name</b><br>
                {safe_html(path.name)}<br><br>

                <b>Type</b><br>
                {safe_html(file_type)}<br><br>

                <b>Size</b><br>
                {get_size(stat.st_size)}<br><br>

                <b>Category</b><br>
                {safe_html(category)}<br><br>

                <b>Original Location</b><br>
                {safe_html(original)}<br><br>

                <b>Current Location</b><br>
                {safe_html(path.resolve())}<br><br>

                <b>Created Time</b><br>
                {safe_html(get_created_time(path))}<br><br>

                <b>Modified Time</b><br>
                {format_time(stat.st_mtime)}<br><br>

                <b>Arrange Time</b><br>
                {safe_html(arrange_time)}<br><br>

                <b>Arrange Type</b><br>
                {safe_html(arrange_type)}<br><br>

                <b>Permissions</b><br>
                {get_permissions(stat.st_mode)}
            """

            self.details.setText(info)

        except (OSError, sqlite3.Error, TypeError, ValueError) as error:
            self.details.setText(
                f"Could not read details: {safe_html(error)}"
            )

    # =====================================================
    # NAVIGATION
    # =====================================================

    def navigate_to(self, folder):

        folder = Path(folder).expanduser()

        if not folder.is_dir():
            QMessageBox.information(
                self,
                "Folder Not Available",
                f"This folder does not exist:\n{folder}"
            )
            return

        self.current_folder = folder
        self.load_files()

    def go_home(self):
        self.navigate_to(Path.home())

    def go_up(self):

        parent = self.current_folder.parent

        if parent != self.current_folder:
            self.navigate_to(parent)

    def open_item(self, item):

        stored_path = item.data(
            Qt.ItemDataRole.UserRole
        )

        if not stored_path:
            return

        path = Path(stored_path)

        if path.is_dir():
            self.navigate_to(path)
        elif path.is_file():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(path))
            )

    # =====================================================
    # CONTEXT MENU
    # =====================================================

    def show_context_menu(self, position):
        clicked_item = self.file_list.itemAt(position)

        if clicked_item is None:
            return

        if not clicked_item.isSelected():
            self.file_list.setCurrentItem(clicked_item)

        menu = QMenu(self)
        arrange_menu = menu.addMenu("📂  Arrange Files")

        auto_action = arrange_menu.addAction("⚡  Auto Arrange")
        manual_action = arrange_menu.addAction("✋  Manual Arrange")

        menu.addSeparator()
        refresh_action = menu.addAction("⟳  Refresh")

        action = menu.exec(self.file_list.mapToGlobal(position))

        if action == auto_action:
            self.arrange_selected_files()
        elif action == manual_action:
            self.manual_arrange_selected_files()
        elif action == refresh_action:
            self.load_files()

    # =====================================================
    # GET SELECTED FILES
    # =====================================================

    def get_selected_regular_files(self):
        selected_files = []

        for item in self.file_list.selectedItems():
            stored_path = item.data(Qt.ItemDataRole.UserRole)

            if stored_path:
                file_path = Path(stored_path)
                if file_path.is_file():
                    selected_files.append(file_path.resolve())

        return selected_files

    # =====================================================
    # AUTO ARRANGE - EXISTING BEHAVIOUR
    # =====================================================

    def arrange_selected_files(self):
        selected_files = self.get_selected_regular_files()

        if not selected_files:
            QMessageBox.information(
                self,
                "Arrange Files",
                "Please select one or more files."
            )
            return

        try:
            from arrange import arrange_selected_files

            count = arrange_selected_files(selected_files)
            self.load_files()

            QMessageBox.information(
                self,
                "Auto Arrange Complete",
                f"Successfully arranged {count} file(s)."
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Arrange Error",
                f"Could not arrange files:\\n{error}"
            )

    # =====================================================
    # MANUAL ARRANGE
    # =====================================================

    def manual_arrange_selected_files(self):
        import json
        import uuid
        from collections import defaultdict

        selected_files = self.get_selected_regular_files()

        if not selected_files:
            QMessageBox.information(
                self,
                "Manual Arrange",
                "Please select one or more files first."
            )
            return

        groups = defaultdict(list)
        for file_path in selected_files:
            extension = file_path.suffix.lower() or "(No extension)"
            groups[extension].append(file_path)

        rules_file = (
            Path.home()
            / ".local/share/smart-file-manager/manual_rules.json"
        )

        try:
            rules = json.loads(rules_file.read_text()) if rules_file.exists() else {}
            if not isinstance(rules, dict):
                rules = {}
        except (OSError, ValueError):
            rules = {}

        dialog = QDialog(self)
        dialog.setWindowTitle("Manual Arrange — Choose Destinations")
        dialog.resize(850, 430)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            "Files are grouped by extension. Choose an existing folder with Browse, "
            "or type a new folder name/path. Relative paths are created inside the "
            "currently open folder."
        ))

        table = QTableWidget(len(groups), 4, dialog)
        table.setHorizontalHeaderLabels(
            ["File type", "Count", "Destination folder", "Browse"]
        )
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        table.setColumnWidth(0, 130)
        table.setColumnWidth(1, 65)
        table.setColumnWidth(3, 90)

        editors = {}
        base_folder = Path(self.current_folder).resolve()

        for row, (extension, files) in enumerate(sorted(groups.items())):
            type_item = QTableWidgetItem(extension)
            count_item = QTableWidgetItem(str(len(files)))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 0, type_item)
            table.setItem(row, 1, count_item)

            default_path = rules.get(extension)
            if not default_path:
                safe_extension = (
                    "no_extension" if extension == "(No extension)"
                    else extension.lstrip(".")
                )
                default_path = str(base_folder / f"Manual_{safe_extension}")

            editor = QLineEdit(str(default_path), table)
            editor.setMinimumHeight(38)
            editor.setStyleSheet("""
                QLineEdit {
                    background-color: #FFFFFF;
                    color: #111827;
                    border: 2px solid #64748B;
                    border-radius: 5px;
                    padding: 6px 10px;
                    selection-background-color: #2563EB;
                    selection-color: #FFFFFF;
                }
                QLineEdit:focus {
                    border: 2px solid #2563EB;
                }
            """)
            editors[extension] = editor
            table.setCellWidget(row, 2, editor)

            browse_button = QPushButton("Browse…", table)

            def choose_folder(checked=False, current_editor=editor):
                folder = QFileDialog.getExistingDirectory(
                    dialog,
                    "Choose Existing Destination Folder",
                    current_editor.text() or str(base_folder)
                )
                if folder:
                    current_editor.setText(folder)

            browse_button.clicked.connect(choose_folder)
            table.setCellWidget(row, 3, browse_button)

        layout.addWidget(table)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Preview Arrangement"
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        destinations = {}
        preview_lines = []
        new_rules = dict(rules)

        for extension, files in sorted(groups.items()):
            raw_destination = editors[extension].text().strip()

            if not raw_destination:
                QMessageBox.warning(
                    self,
                    "Missing Destination",
                    f"Please choose a destination for {extension} files."
                )
                return

            destination_folder = Path(raw_destination).expanduser()
            if not destination_folder.is_absolute():
                destination_folder = base_folder / destination_folder
            destination_folder = destination_folder.resolve()

            destinations[extension] = destination_folder
            new_rules[extension] = str(destination_folder)

            for file_path in files:
                preview_lines.append(
                    f"{file_path.name}  →  {destination_folder / file_path.name}"
                )

        preview_text = "\\n".join(preview_lines)
        if len(preview_text) > 12000:
            preview_text = preview_text[:12000] + "\\n... (preview shortened)"

        answer = QMessageBox.question(
            self,
            "Confirm Manual Arrangement",
            "Preview of selected files and their destinations:\\n\\n"
            + preview_text
            + "\\n\\nContinue with these moves?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        from arrange import move_file_to_destination

        operation_id = str(uuid.uuid4())
        moved_count = 0
        errors = []

        for extension, files in groups.items():
            destination_folder = destinations[extension]

            for file_path in files:
                info, error = move_file_to_destination(
                    file_path,
                    destination_folder,
                    operation_id=operation_id
                )
                if info:
                    moved_count += 1
                if error:
                    errors.append(error)

        try:
            rules_file.parent.mkdir(parents=True, exist_ok=True)
            rules_file.write_text(
                json.dumps(new_rules, indent=2, ensure_ascii=False)
            )
        except OSError as error:
            errors.append(f"Could not save reusable rules: {error}")

        self.load_files()

        message = f"Successfully moved {moved_count} file(s)."
        if errors:
            message += "\\n\\nSome files could not be moved:\\n" + "\\n".join(errors[:15])

        QMessageBox.information(self, "Manual Arrange Complete", message)

    # =====================================================
    # ARRANGEMENT HISTORY
    # =====================================================

    def show_empty_folder_cleaner(self):
        dialog = EmptyFolderCleanerDialog(self)
        dialog.exec()

    def show_large_file_finder(self):
        dialog = LargeFileFinderDialog(self)
        dialog.exec()

    def show_duplicate_file_finder(self):
        dialog = DuplicateFileFinderDialog(self)
        dialog.exec()

    def show_archive_manager(self):
        dialog = ArchiveManagerDialog(self)
        dialog.exec()

    def show_permission_manager(self):
        dialog = PermissionManagerDialog(self)
        dialog.exec()

    def show_password_protection(self):
        dialog = PasswordProtectionDialog(self)
        dialog.exec()


    # =====================================================
    # UNDO LAST ARRANGEMENT
    # =====================================================

    def undo_last_arrangement(self, dialog=None):
        try:
            rows = database.get_latest_undoable_operation()
        except sqlite3.Error as error:
            QMessageBox.critical(self, "Undo Error", str(error))
            return

        if not rows:
            QMessageBox.information(
                self,
                "Undo Arrangement",
                "There is no arrangement available to undo."
            )
            return

        arrange_type = rows[0]["arrange_type"] or "Arrangement"

        answer = QMessageBox.question(
            self,
            "Confirm Undo",
            f"Undo the latest {arrange_type} operation?\\n\\n"
            f"{len(rows)} file(s) will be restored to their original locations.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        restored = 0
        errors = []

        for row in rows:
            try:
                destination = Path(row["destination_location"]).expanduser()
                original = Path(row["original_location"]).expanduser()

                if not destination.is_file():
                    raise FileNotFoundError(
                        f"Arranged file not found: {destination}"
                    )

                if original.exists():
                    raise FileExistsError(
                        f"Original location already contains a file: {original}"
                    )

                original.parent.mkdir(parents=True, exist_ok=True)

                shutil.move(str(destination), str(original))

                database.update_file_location_after_undo(
                    str(destination),
                    str(original)
                )

                database.mark_history_as_undone(row["id"])
                restored += 1

            except Exception as error:
                errors.append(f"{row['file_name']}: {error}")

        self.load_files()

        if dialog is not None:
            dialog.close()

        self.show_history()

        message = f"Successfully restored {restored} file(s)."

        if errors:
            message += "\\n\\nCould not restore some files:\\n"
            message += "\\n".join(errors[:10])

        QMessageBox.information(self, "Undo Result", message)

    def show_history(self):

        try:
            rows = database.get_arrangement_history(
                limit=500
            )

        except sqlite3.Error as error:
            QMessageBox.critical(
                self,
                "Database Error",
                str(error)
            )
            return

        dialog = QWidget(self)
        dialog.setWindowTitle("Arrangement History")
        dialog.resize(1500, 850)
        dialog.setWindowFlag(Qt.WindowType.Window, True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        title = QLabel("Arrangement History")
        title.setObjectName("PanelTitle")
        title.setStyleSheet("font-size: 15pt;")
        layout.addWidget(title)

        class ResponsiveHistoryTable(QTableWidget):

            def resizeEvent(self, event):
                super().resizeEvent(event)
                self.adjust_history_columns()

            def adjust_history_columns(self):
                if self.columnCount() != 8:
                    return

                weights = [1.2, 2.1, 2.1, 0.65, 0.9, 1.4, 0.75, 1.1]
                available_width = self.viewport().width()

                if available_width <= 0:
                    return

                total = sum(weights)
                widths = [
                    int(available_width * weight / total)
                    for weight in weights
                ]
                widths[-1] += available_width - sum(widths)

                for index, width in enumerate(widths):
                    self.setColumnWidth(index, width)

        table = ResponsiveHistoryTable()
        table.setColumnCount(8)

        table.setHorizontalHeaderLabels([
            "File Name",
            "Original Location",
            "Destination",
            "Size",
            "Category",
            "Arrange Time",
            "Status",
            "Arrange Type"
        ])

        table.setRowCount(len(rows))
        table.setAlternatingRowColors(True)
        table.setFont(QFont("Ubuntu", 10))
        table.setWordWrap(False)
        table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        table.setTextElideMode(Qt.TextElideMode.ElideRight)
        table.verticalHeader().setDefaultSectionSize(30)
        table.verticalHeader().setMinimumSectionSize(26)
        table.verticalHeader().setVisible(False)

        table.setStyleSheet("""
            QTableWidget {
                font-size: 10pt;
                gridline-color: #64748B;
            }
            QHeaderView::section {
                font-size: 10pt;
                padding: 5px;
            }
        """)

        table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )

        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )

        for row_index, row in enumerate(rows):

            values = [
                row["file_name"],
                row["original_location"] or "",
                row["destination_location"] or "",
                get_size(row["file_size"] or 0),
                row["category"] or "",
                row["arrange_time"] or "",
                row["status"] or "",
                row["arrange_type"] or "Auto Arrange"
            ]

            for col_index, value in enumerate(values):

                cell = QTableWidgetItem(str(value))

                cell.setToolTip(str(value))

                table.setItem(
                    row_index,
                    col_index,
                    cell
                )

        header = table.horizontalHeader()
        header.setFont(QFont("Ubuntu", 10))
        header.setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        table.adjust_history_columns()

        layout.addWidget(table)

        button_layout = QHBoxLayout()

        undo_button = QPushButton("Undo Last Arrange")
        undo_button.clicked.connect(
            lambda: self.undo_last_arrangement(dialog)
        )

        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.close)

        button_layout.addWidget(undo_button)
        button_layout.addStretch()
        button_layout.addWidget(close_button)

        layout.addLayout(button_layout)

        dialog.setStyleSheet(
            self.styleSheet() + """
                QTableWidget {
                    font-size: 10pt;
                }
                QHeaderView::section {
                    font-size: 10pt;
                    padding: 5px;
                }
            """
        )

        dialog.showMaximized()

        self.history_dialog = dialog

    # =====================================================
    # CLOSE
    # =====================================================

    def closeEvent(self, event):
        event.accept()


# =========================================================
# PROGRAM START
# =========================================================

def main():

    # Command-line mode for Nautilus selected files.
    if len(sys.argv) > 1:
        from arrange import arrange_selected_files
        arrange_selected_files(sys.argv[1:])
        return

    app = QApplication(sys.argv)

    app.setApplicationName("Smart File Manager")
    app.setFont(QFont("Ubuntu", 10))

    window = FileManager()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

    def open_file(self, item):
        location_item = self.table.item(item.row(), 1)

        if location_item is None:
            return

        path = Path(location_item.text())

        if not path.is_file():
            QMessageBox.warning(
                self, "File Not Found",
                f"File does not exist:\n{path}"
            )
            return

        self.status.setText(f"Opening: {path.name}")

        try:
            result = subprocess.run(
                ["gio", "open", str(path)],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                QMessageBox.warning(
                    self,
                    "Cannot Open File",
                    result.stderr or "Ubuntu could not open this file."
                )

        except subprocess.TimeoutExpired:
            QMessageBox.warning(
                self, "Open Timeout",
                "File opening took too long."
            )
    def open_file(self, item):
        location_item = self.table.item(item.row(), 1)

        if location_item is None:
            return

        path = Path(location_item.text())

        if not path.is_file():
            QMessageBox.warning(
                self, "File Not Found",
                f"File does not exist:\n{path}"
            )
            return

        self.status.setText(f"Opening: {path.name}")

        try:
            result = subprocess.run(
                ["gio", "open", str(path)],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                QMessageBox.warning(
                    self,
                    "Cannot Open File",
                    result.stderr or "Ubuntu could not open this file."
                )

        except subprocess.TimeoutExpired:
            QMessageBox.warning(
                self, "Open Timeout",
                "File opening took too long."
            )

        except OSError as error:
            QMessageBox.warning(
                self, "Open Error", str(error)
            )
        except OSError as error:
            QMessageBox.warning(
                self, "Open Error", str(error)
            )
    def open_file(self, item):
        location_item = self.table.item(item.row(), 1)

        if location_item is None:
            return

        path = Path(location_item.text())

        if not path.is_file():
            QMessageBox.warning(
                self, "File Not Found",
                f"File does not exist:\n{path}"
            )
            return

        self.status.setText(f"Opening: {path.name}")

        try:
            result = subprocess.run(
                ["gio", "open", str(path)],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                QMessageBox.warning(
                    self,
                    "Cannot Open File",
                    result.stderr or "Ubuntu could not open this file."
                )

        except subprocess.TimeoutExpired:
            QMessageBox.warning(
                self, "Open Timeout",
                "File opening took too long."
            )

        except OSError as error:
            QMessageBox.warning(
                self, "Open Error", str(error)
            )
