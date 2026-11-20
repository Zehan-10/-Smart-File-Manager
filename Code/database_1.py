import sqlite3
from pathlib import Path
from datetime import datetime


# Database location
DATABASE_DIR = Path.home() / ".local" / "share" / "smart-file-manager"
DATABASE_FILE = DATABASE_DIR / "smart_file_manager.db"


def get_connection():
    """Connect to the SQLite database."""
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row

    return connection


def initialize_database():
    """Create database tables if they do not exist."""

    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_key TEXT UNIQUE,
                file_name TEXT NOT NULL,
                file_type TEXT,
                file_size INTEGER DEFAULT 0,
                original_location TEXT,
                current_location TEXT NOT NULL,
                modified_time TEXT,
                arrange_time TEXT,
                category TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS arrangement_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                original_location TEXT,
                destination_location TEXT,
                file_size INTEGER DEFAULT 0,
                category TEXT,
                arrange_time TEXT NOT NULL,
                status TEXT NOT NULL,
                arrange_type TEXT NOT NULL DEFAULT 'Auto Arrange',
                operation_id TEXT
            )
        """)

        columns = [
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(arrangement_history)"
            ).fetchall()
        ]

        if "operation_id" not in columns:
            connection.execute(
                "ALTER TABLE arrangement_history ADD COLUMN operation_id TEXT"
            )

        # Save the first original permissions for future restoration.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS permission_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL UNIQUE,
                original_mode INTEGER NOT NULL,
                original_uid INTEGER NOT NULL,
                original_gid INTEGER NOT NULL,
                original_owner TEXT,
                original_group TEXT,
                saved_at TEXT NOT NULL,
                is_directory INTEGER DEFAULT 0
            )
        """)

        # Keep a permanent history of permission changes.
        connection.execute("""
            CREATE TABLE IF NOT EXISTS permission_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                old_mode INTEGER,
                new_mode INTEGER,
                old_uid INTEGER,
                new_uid INTEGER,
                old_gid INTEGER,
                new_gid INTEGER,
                permission_mode TEXT,
                recursive INTEGER DEFAULT 0,
                changed_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'SUCCESS'
            )
        """)

        connection.commit()


def save_arranged_file(
    file_key,
    file_name,
    file_type,
    file_size,
    original_location,
    current_location,
    modified_time,
    arrange_time,
    category
):
    """Save or update the details of an arranged file."""

    with get_connection() as connection:
        connection.execute("""
            INSERT INTO files (
                file_key,
                file_name,
                file_type,
                file_size,
                original_location,
                current_location,
                modified_time,
                arrange_time,
                category
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(file_key) DO UPDATE SET
                file_name = excluded.file_name,
                file_type = excluded.file_type,
                file_size = excluded.file_size,
                current_location = excluded.current_location,
                modified_time = excluded.modified_time,
                arrange_time = excluded.arrange_time,
                category = excluded.category
        """, (
            file_key,
            file_name,
            file_type,
            file_size,
            original_location,
            current_location,
            modified_time,
            arrange_time,
            category
        ))

        connection.commit()


def save_arrangement_history(
    file_name,
    original_location,
    destination_location,
    file_size,
    category,
    arrange_time,
    status="SUCCESS",
    arrange_type="Auto Arrange",
    operation_id=None
):
    """Save one arrangement operation to the history table."""

    with get_connection() as connection:
        connection.execute("""
            INSERT INTO arrangement_history (
                file_name,
                original_location,
                destination_location,
                file_size,
                category,
                arrange_time,
                status,
                arrange_type,
                operation_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            file_name,
            original_location,
            destination_location,
            file_size,
            category,
            arrange_time,
            status,
            arrange_type,
            operation_id
        ))

        connection.commit()


def get_file_details(file_path):
    """Get saved details for a file using its current path."""

    path = str(Path(file_path).resolve())

    with get_connection() as connection:
        return connection.execute("""
            SELECT *
            FROM files
            WHERE current_location = ?
            ORDER BY id DESC
            LIMIT 1
        """, (path,)).fetchone()


def get_arrangement_history(limit=500):
    """Return recent arrangement history."""

    with get_connection() as connection:
        return connection.execute("""
            SELECT *
            FROM arrangement_history
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()


def get_all_saved_files(limit=1000):
    """Return recently saved file details."""

    with get_connection() as connection:
        return connection.execute("""
            SELECT *
            FROM files
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()


def get_database_path():
    """Return the database file location."""
    return str(DATABASE_FILE)


def get_file_arrange_type(file_path):
    """Get the latest arrangement type for a file's current path."""

    path = str(Path(file_path).resolve())

    with get_connection() as connection:
        return connection.execute("""
            SELECT arrange_type
            FROM arrangement_history
            WHERE destination_location = ?
            ORDER BY id DESC
            LIMIT 1
        """, (path,)).fetchone()


def delete_records_for_deleted_folder(folder_path):
    """
    Delete database records whose current file locations
    are inside the deleted folder.

    Arrangement history is preserved.
    """

    folder = str(Path(folder_path).resolve())
    prefix = folder.rstrip("/") + "/"

    with get_connection() as connection:
        connection.execute("""
            DELETE FROM files
            WHERE current_location = ?
               OR substr(current_location, 1, ?) = ?
        """, (
            folder,
            len(prefix),
            prefix
        ))

        connection.commit()


# Create tables when this module is first used.
initialize_database()

def get_latest_undoable_operation():
    """Return successful history rows from the latest undoable operation."""

    with get_connection() as connection:
        latest = connection.execute("""
            SELECT operation_id
            FROM arrangement_history
            WHERE status = 'SUCCESS'
              AND operation_id IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()

        if latest is None:
            return []

        return connection.execute("""
            SELECT *
            FROM arrangement_history
            WHERE operation_id = ?
              AND status = 'SUCCESS'
            ORDER BY id DESC
        """, (latest["operation_id"],)).fetchall()


def mark_history_as_undone(history_id):
    """Mark one successfully restored history row as undone."""

    with get_connection() as connection:
        connection.execute("""
            UPDATE arrangement_history
            SET status = 'UNDONE'
            WHERE id = ? AND status = 'SUCCESS'
        """, (history_id,))
        connection.commit()


def update_file_location_after_undo(destination, original):
    """Update the saved file record after restoring its original location."""

    original_path = Path(original)

    with get_connection() as connection:
        connection.execute("""
            UPDATE files
            SET file_name = ?,
                current_location = ?,
                category = ?
            WHERE current_location = ?
        """, (
            original_path.name,
            str(original_path),
            original_path.parent.name,
            str(Path(destination).resolve())
        ))
        connection.commit()



# =========================================================
# PERMISSION MANAGER DATABASE FUNCTIONS
# =========================================================

def save_original_permission(
    file_path,
    mode,
    uid,
    gid,
    owner=None,
    group=None,
    is_directory=False
):
    """Save the first original permission without overwriting it."""

    path = str(Path(file_path).expanduser().resolve())

    with get_connection() as connection:
        connection.execute("""
            INSERT OR IGNORE INTO permission_records (
                file_path,
                original_mode,
                original_uid,
                original_gid,
                original_owner,
                original_group,
                saved_at,
                is_directory
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            path,
            mode,
            uid,
            gid,
            owner,
            group,
            datetime.now().isoformat(timespec="seconds"),
            int(is_directory)
        ))

        connection.commit()


def get_original_permission(file_path):
    """Get the saved original permission of a file or folder."""

    path = str(Path(file_path).expanduser().resolve())

    with get_connection() as connection:
        return connection.execute("""
            SELECT *
            FROM permission_records
            WHERE file_path = ?
        """, (path,)).fetchone()


def save_permission_history(
    file_path,
    old_mode,
    new_mode,
    old_uid,
    new_uid,
    old_gid,
    new_gid,
    permission_mode="Custom",
    recursive=False,
    status="SUCCESS"
):
    """Save one permission change in history."""

    path = str(Path(file_path).expanduser().resolve())

    with get_connection() as connection:
        connection.execute("""
            INSERT INTO permission_history (
                file_path,
                old_mode,
                new_mode,
                old_uid,
                new_uid,
                old_gid,
                new_gid,
                permission_mode,
                recursive,
                changed_at,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            path,
            old_mode,
            new_mode,
            old_uid,
            new_uid,
            old_gid,
            new_gid,
            permission_mode,
            int(recursive),
            datetime.now().isoformat(timespec="seconds"),
            status
        ))

        connection.commit()


def get_permission_history(file_path=None, limit=500):
    """Return permission history, optionally for one path."""

    with get_connection() as connection:
        if file_path is not None:
            path = str(Path(file_path).expanduser().resolve())

            return connection.execute("""
                SELECT *
                FROM permission_history
                WHERE file_path = ?
                ORDER BY id DESC
                LIMIT ?
            """, (path, limit)).fetchall()

        return connection.execute("""
            SELECT *
            FROM permission_history
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()
