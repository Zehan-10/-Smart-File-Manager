import os
import hashlib
from collections import defaultdict
from pathlib import Path


# =====================================================
# SCAN SETTINGS
# =====================================================

CHUNK_SIZE = 1024 * 1024

EXCLUDED_DIRECTORIES = {
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/tmp",
    "/var/tmp",
    "/lost+found",
}


# =====================================================
# FILE HASH
# =====================================================

def calculate_file_hash(file_path):

    sha256 = hashlib.sha256()

    try:
        with open(file_path, "rb") as file:

            while True:
                chunk = file.read(CHUNK_SIZE)

                if not chunk:
                    break

                sha256.update(chunk)

        return sha256.hexdigest()

    except (OSError, PermissionError):
        return None


# =====================================================
# DUPLICATE FILE SCANNER
# =====================================================

def calculate_partial_hash(file_path, file_size):
    """Quickly compare the beginning and end of same-size files."""
    sha256 = hashlib.sha256()
    sample_size = 64 * 1024

    try:
        with open(file_path, "rb") as file:
            if file_size <= sample_size * 2:
                sha256.update(file.read())
            else:
                sha256.update(file.read(sample_size))
                file.seek(-sample_size, os.SEEK_END)
                sha256.update(file.read(sample_size))

        return sha256.hexdigest()

    except OSError:
        return None


def scan_duplicates(folder_path, progress_callback=None, cancel_check=None):
    folder_path = Path(folder_path).resolve()

    files_by_size = defaultdict(list)
    scanned_count = 0
    skipped_count = 0

    # STEP 1: Group files by size.
    for root, directories, files in os.walk(
        folder_path, topdown=True, followlinks=False
    ):
        if cancel_check and cancel_check():
            break

        root_path = Path(root)

        directories[:] = [
            directory for directory in directories
            if not (root_path / directory).is_symlink()
            and str(root_path / directory) not in EXCLUDED_DIRECTORIES
        ]

        for filename in files:
            if cancel_check and cancel_check():
                break

            file_path = root_path / filename

            try:
                if file_path.is_symlink():
                    skipped_count += 1
                    continue

                file_size = file_path.stat().st_size

                if file_size == 0:
                    skipped_count += 1
                    continue

                files_by_size[file_size].append(str(file_path))
                scanned_count += 1

                if progress_callback:
                    progress_callback(scanned_count, str(file_path))

            except OSError:
                skipped_count += 1

    # STEP 2: Quick partial hash.
    partial_groups = defaultdict(list)

    for file_size, paths in files_by_size.items():
        if cancel_check and cancel_check():
            break

        if len(paths) < 2:
            continue

        for file_path in paths:
            if cancel_check and cancel_check():
                break

            partial_hash = calculate_partial_hash(file_path, file_size)

            if partial_hash:
                partial_groups[(file_size, partial_hash)].append(file_path)

    # STEP 3: Full SHA-256 verification.
    duplicate_hashes = defaultdict(list)

    for (file_size, partial_hash), paths in partial_groups.items():
        if cancel_check and cancel_check():
            break

        if len(paths) < 2:
            continue

        for file_path in paths:
            if cancel_check and cancel_check():
                break

            full_hash = calculate_file_hash(file_path)

            if full_hash:
                duplicate_hashes[(file_size, full_hash)].append(file_path)

    duplicate_groups = []

    for (file_size, file_hash), paths in duplicate_hashes.items():
        if len(paths) < 2:
            continue

        duplicate_groups.append({
            "hash": file_hash,
            "size": file_size,
            "files": sorted(paths)
        })

    duplicate_groups.sort(
        key=lambda group: group["size"],
        reverse=True
    )

    return {
        "groups": duplicate_groups,
        "scanned": scanned_count,
        "skipped": skipped_count
    }
