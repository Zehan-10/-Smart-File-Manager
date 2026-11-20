from pathlib import Path
from datetime import datetime
import shutil
import sys
import uuid

import database


# =====================================================
# FILE CATEGORIES
# =====================================================

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
        ".mp3", ".wav", ".flac", ".aac",
        ".ogg", ".m4a"
    ],
    "Videos": [
        ".mp4", ".mkv", ".avi", ".mov",
        ".wmv", ".webm"
    ],
    "Code": [
        ".py", ".c", ".cpp", ".java",
        ".js", ".html", ".css", ".php",
        ".json", ".xml", ".sh"
    ]
}


# =====================================================
# HELPER FUNCTIONS
# =====================================================

def get_category(file_path):
    extension = Path(file_path).suffix.lower()

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


def get_file_key(file_path):
    path = Path(file_path)

    try:
        stat = path.stat()
        return f"{stat.st_dev}:{stat.st_ino}"
    except OSError:
        return str(path.resolve())


def get_time():
    return (
        datetime.now()
        .astimezone()
        .strftime("%d-%m-%Y %I:%M:%S %p %z")
    )


def get_modified_time(file_path):
    try:
        return (
            datetime.fromtimestamp(
                Path(file_path).stat().st_mtime
            )
            .astimezone()
            .strftime("%d-%m-%Y %I:%M:%S %p %z")
        )
    except OSError:
        return ""


# =====================================================
# MOVE ONE FILE AND SAVE TO SQLITE
# =====================================================

def move_file(file_path, operation_id=None):
    file = Path(file_path)

    if not file.is_absolute():
        file = (Path.cwd() / file).resolve()

    if not file.exists():
        return None, f"{file} (File not found)"

    if not file.is_file():
        return None, f"{file} (Not a regular file)"

    original_location = str(file.resolve())

    try:
        file_stat = file.stat()
        file_size = file_stat.st_size
        file_type = file.suffix.lower() if file.suffix else "File"
        modified_time = get_modified_time(file)
        category = get_category(file)

        destination_folder = file.parent / category

        destination_folder.mkdir(
            parents=True,
            exist_ok=True
        )

        destination = destination_folder / file.name

        # Already in its category folder
        if destination.resolve() == file.resolve():
            return None, f"{file.name} (Already arranged)"

        # Do not overwrite existing files
        if destination.exists():
            counter = 1

            while destination.exists():
                destination = (
                    destination_folder
                    / f"{file.stem}_{counter}{file.suffix}"
                )
                counter += 1

        shutil.move(str(file), str(destination))

        arrange_time = get_time()
        destination_location = str(destination.resolve())
        file_key = get_file_key(destination)

        # Save current file details
        database.save_arranged_file(
            file_key=file_key,
            file_name=destination.name,
            file_type=file_type,
            file_size=file_size,
            original_location=original_location,
            current_location=destination_location,
            modified_time=modified_time,
            arrange_time=arrange_time,
            category=category
        )

        # Save a separate history record for this arrangement
        database.save_arrangement_history(
            file_name=destination.name,
            original_location=original_location,
            destination_location=destination_location,
            file_size=file_size,
            category=category,
            arrange_time=arrange_time,
            status="SUCCESS",
            arrange_type="Auto Arrange",
            operation_id=operation_id
        )

        return {
            "name": destination.name,
            "size": file_size,
            "category": category,
            "original_location": original_location,
            "destination": destination_location,
            "arrange_time": arrange_time
        }, None

    except Exception as error:
        return None, f"{file.name} ({error})"


# =====================================================
# ARRANGEMENT REPORT
# =====================================================

def print_report(moved_files, skipped_files, arrangement_time):
    print("\n" + "=" * 50)
    print("             ARRANGEMENT REPORT")
    print("=" * 50)

    print(f"Time: {arrangement_time}")
    print(f"Files moved: {len(moved_files)}")

    for number, info in enumerate(moved_files, start=1):
        print(f"\n--- File {number} ---")
        print(f"Name: {info['name']}")
        print(f"Size: {get_size(info['size'])}")
        print(f"Category: {info['category']}")
        print(f"Original location: {info['original_location']}")
        print(f"Destination: {info['destination']}")
        print(f"Arrange time: {info['arrange_time']}")

    if skipped_files:
        print("\nFiles skipped or failed:")
        for item in skipped_files:
            print(f"- {item}")

    print("\n" + "=" * 50)


# =====================================================
# ARRANGE SELECTED FILES
# =====================================================

def arrange_selected_files(file_paths):
    operation_id = str(uuid.uuid4())
    arrangement_time = get_time()
    moved_files = []
    skipped_files = []

    for file_path in file_paths:
        info, error = move_file(
            file_path,
            operation_id=operation_id
        )

        if info:
            moved_files.append(info)

        if error:
            skipped_files.append(error)

    print_report(
        moved_files,
        skipped_files,
        arrangement_time
    )

    return len(moved_files)


# =====================================================
# ARRANGE AN ENTIRE FOLDER
# =====================================================

def arrange_folder(folder_path):
    folder = Path(folder_path).resolve()

    if not folder.is_dir():
        print(f"Folder not found: {folder}")
        return 0

    # Only direct files are processed; subfolders are not traversed.
    files = [
        item for item in folder.iterdir()
        if item.is_file()
    ]

    return arrange_selected_files(files)


# =====================================================
# PROGRAM START
# =====================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("No files selected. Nothing was arranged.")

    elif len(sys.argv) == 2:
        supplied_path = Path(sys.argv[1])

        if not supplied_path.is_absolute():
            supplied_path = (Path.cwd() / supplied_path).resolve()

        if supplied_path.is_dir():
            arrange_folder(supplied_path)
        else:
            arrange_selected_files([supplied_path])

    else:
        arrange_selected_files(sys.argv[1:])


# =====================================================
# MANUAL ARRANGE - MOVE TO A CHOSEN DESTINATION
# =====================================================

def move_file_to_destination(file_path, destination_folder, operation_id=None):
    """Move one selected file to a user-chosen folder and save its history."""
    file = Path(file_path).resolve()
    destination_folder = Path(destination_folder).expanduser().resolve()

    if not file.exists():
        return None, f"{file.name} (File not found)"

    if not file.is_file():
        return None, f"{file.name} (Not a regular file)"

    original_location = str(file)
    destination = destination_folder / file.name

    if destination.resolve() == file:
        return None, f"{file.name} (Already in this folder)"

    try:
        file_stat = file.stat()
        file_size = file_stat.st_size
        file_type = file.suffix.lower() if file.suffix else "File"
        modified_time = get_modified_time(file)

        destination_folder.mkdir(parents=True, exist_ok=True)

        # Never overwrite an existing file.
        if destination.exists():
            counter = 1
            while destination.exists():
                destination = (
                    destination_folder
                    / f"{file.stem}_{counter}{file.suffix}"
                )
                counter += 1

        shutil.move(str(file), str(destination))

        arrange_time = get_time()
        destination_location = str(destination.resolve())
        file_key = get_file_key(destination)
        category = destination.parent.name

        database.save_arranged_file(
            file_key=file_key,
            file_name=destination.name,
            file_type=file_type,
            file_size=file_size,
            original_location=original_location,
            current_location=destination_location,
            modified_time=modified_time,
            arrange_time=arrange_time,
            category=category
        )

        database.save_arrangement_history(
            file_name=destination.name,
            original_location=original_location,
            destination_location=destination_location,
            file_size=file_size,
            category=category,
            arrange_time=arrange_time,
            status="SUCCESS",
            arrange_type="Manual Arrange",
            operation_id=operation_id
        )

        return {
            "name": destination.name,
            "size": file_size,
            "category": category,
            "original_location": original_location,
            "destination": destination_location,
            "arrange_time": arrange_time
        }, None

    except Exception as error:
        return None, f"{file.name} ({error})"
