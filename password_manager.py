import os
import stat
import uuid
import hashlib
import zipfile
import tempfile
import subprocess

from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


MAGIC = b"SFMENC1"
SALT_SIZE = 16
NONCE_SIZE = 12
TAG_SIZE = 16
CHUNK_SIZE = 1024 * 1024
ITERATIONS = 600000
EXTENSION = ".sfmenc"


def _derive_key(password, salt):
    if not password:
        raise ValueError("Password cannot be empty.")

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=ITERATIONS
    )
    return kdf.derive(password.encode("utf-8"))


def _encrypt_stream(source, destination, password, kind):
    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    key = _derive_key(password, salt)

    encryptor = Cipher(
        algorithms.AES(key),
        modes.GCM(nonce)
    ).encryptor()

    header = MAGIC + kind + salt + nonce
    encryptor.authenticate_additional_data(header)

    with open(source, "rb") as src:
        dst_fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600
        )

        with os.fdopen(dst_fd, "wb") as dst:
            dst.write(header)

            while True:
                chunk = src.read(CHUNK_SIZE)
                if not chunk:
                    break
                dst.write(encryptor.update(chunk))

            dst.write(encryptor.finalize())
            dst.write(encryptor.tag)


def _decrypt_stream(source, destination, password):
    with open(source, "rb") as src:
        header_size = len(MAGIC) + 1 + SALT_SIZE + NONCE_SIZE
        header = src.read(header_size)

        if len(header) != header_size or not header.startswith(MAGIC):
            raise ValueError("Invalid or unsupported encrypted file.")

        kind = header[len(MAGIC):len(MAGIC) + 1]
        if kind not in (b"F", b"D"):
            raise ValueError("Unknown encrypted content type.")

        offset = len(MAGIC) + 1
        salt = header[offset:offset + SALT_SIZE]
        nonce = header[offset + SALT_SIZE:offset + SALT_SIZE + NONCE_SIZE]

        src.seek(0, os.SEEK_END)
        file_size = src.tell()

        if file_size < header_size + TAG_SIZE:
            raise ValueError("Encrypted file is incomplete.")

        src.seek(file_size - TAG_SIZE)
        tag = src.read(TAG_SIZE)

        ciphertext_size = file_size - header_size - TAG_SIZE
        src.seek(header_size)

        key = _derive_key(password, salt)

        decryptor = Cipher(
            algorithms.AES(key),
            modes.GCM(nonce, tag)
        ).decryptor()

        decryptor.authenticate_additional_data(header)

        remaining = ciphertext_size

        with open(destination, "xb") as dst:
            while remaining:
                chunk = src.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise ValueError("Encrypted file is incomplete.")

                remaining -= len(chunk)
                dst.write(decryptor.update(chunk))

            dst.write(decryptor.finalize())

    return kind


def _make_folder_archive(folder, archive_path):
    folder = Path(folder)

    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:

        archive.write(folder, folder.name)

        for root, dirs, files in os.walk(folder, followlinks=False):
            for name in list(dirs) + list(files):
                item = Path(root) / name
                item_stat = item.lstat()

                if stat.S_ISLNK(item_stat.st_mode):
                    raise ValueError(
                        f"Symbolic links are not supported: {item}"
                    )

                if stat.S_ISDIR(item_stat.st_mode):
                    if name in dirs:
                        archive.write(
                            item, item.relative_to(folder.parent)
                        )

                elif stat.S_ISREG(item_stat.st_mode):
                    if name in files:
                        archive.write(
                            item, item.relative_to(folder.parent)
                        )

                else:
                    raise ValueError(
                        f"Unsupported special file found: {item}"
                    )


def _safe_extract(archive_path, destination):
    destination = Path(destination).resolve()

    with zipfile.ZipFile(archive_path, "r") as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise ValueError("Folder archive verification failed.")

        for item in archive.infolist():
            target = (destination / item.filename).resolve()

            if os.path.commonpath(
                [str(destination), str(target)]
            ) != str(destination):
                raise ValueError("Unsafe path found inside archive.")

            unix_mode = item.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise ValueError("Symbolic links are not supported.")

        archive.extractall(destination)


def _verify_encrypted(encrypted_path, password, expected_kind):
    fd, temp_path = tempfile.mkstemp(prefix="sfm_verify_")
    os.close(fd)
    os.remove(temp_path)

    try:
        kind = _decrypt_stream(
            encrypted_path, temp_path, password
        )

        if kind != expected_kind:
            raise ValueError("Encrypted content type mismatch.")

        if kind == b"D":
            with zipfile.ZipFile(temp_path, "r") as archive:
                bad_file = archive.testzip()
                if bad_file:
                    raise ValueError("Folder verification failed.")

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def protect_path(path, password):
    import shutil

    path = Path(path).expanduser().absolute()

    if not path.exists():
        raise FileNotFoundError("Selected file or folder does not exist.")
    if path.is_symlink():
        raise ValueError("Symbolic links cannot be protected.")
    if path == Path.home() or path == Path("/"):
        raise ValueError("Home and system root cannot be protected.")
    if path.name.endswith(EXTENSION):
        raise ValueError("This file is already an encrypted file.")
    if not path.is_file() and not path.is_dir():
        raise ValueError("Only regular files and folders can be protected.")

    if path.is_file():
        with path.open("rb") as f:
            if f.read(len(MAGIC)) == MAGIC:
                raise ValueError("This file is already protected.")

    is_folder = path.is_dir()
    kind = b"D" if is_folder else b"F"

    archive_path = None
    temp_output = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    backup = path.with_name("." + path.name + ".sfm-original-" + uuid.uuid4().hex)

    try:
        source = path

        if is_folder:
            fd, archive_path = tempfile.mkstemp(
                prefix="sfm_folder_", suffix=".zip", dir=str(path.parent)
            )
            os.close(fd)
            _make_folder_archive(path, archive_path)
            source = Path(archive_path)

        _encrypt_stream(source, temp_output, password, kind)
        _verify_encrypted(temp_output, password, kind)

        os.replace(path, backup)
        try:
            os.replace(temp_output, path)
        except Exception:
            os.replace(backup, path)
            raise

        try:
            if is_folder:
                shutil.rmtree(backup)
            else:
                backup.unlink()
        except Exception as error:
            return {
                "success": True,
                "encrypted_path": str(path),
                "message": "Protected, but temporary plaintext backup could not be removed: " + str(error)
            }

        return {
            "success": True,
            "encrypted_path": str(path),
            "message": "Protected successfully at the original location."
        }

    finally:
        for temporary in (archive_path, str(temp_output)):
            if temporary and os.path.exists(temporary):
                os.remove(temporary)

def unlock_file(encrypted_path, password):
    import shutil

    encrypted_path = Path(encrypted_path).expanduser().absolute()

    if not encrypted_path.is_file():
        raise FileNotFoundError("Protected file not found.")

    is_legacy = encrypted_path.name.endswith(EXTENSION)

    if is_legacy:
        output_path = encrypted_path.with_name(
            encrypted_path.name[:-len(EXTENSION)]
        )
        if output_path.exists():
            raise FileExistsError(f"Output already exists: {output_path}")
    else:
        output_path = encrypted_path

    fd, temp_payload = tempfile.mkstemp(
        prefix="sfm_unlock_", dir=str(encrypted_path.parent)
    )
    os.close(fd)
    os.remove(temp_payload)

    staging = encrypted_path.parent / (".sfm_restore_" + uuid.uuid4().hex)
    encrypted_backup = encrypted_path.with_name(
        "." + encrypted_path.name + ".sfm-encrypted-" + uuid.uuid4().hex
    )

    try:
        kind = _decrypt_stream(encrypted_path, temp_payload, password)

        if kind == b"F":
            os.replace(temp_payload, output_path)

        elif kind == b"D":
            staging.mkdir(mode=0o700)
            _safe_extract(temp_payload, staging)

            restored_folder = staging / output_path.name
            if not restored_folder.is_dir():
                raise ValueError("Original folder structure is missing.")

            if is_legacy:
                os.replace(restored_folder, output_path)
            else:
                os.replace(encrypted_path, encrypted_backup)
                try:
                    os.replace(restored_folder, encrypted_path)
                except Exception:
                    os.replace(encrypted_backup, encrypted_path)
                    raise

                try:
                    encrypted_backup.unlink()
                except Exception as error:
                    return {
                        "success": True,
                        "restored_path": str(output_path),
                        "message": "Unlocked, but encrypted backup could not be removed: " + str(error)
                    }
        else:
            raise ValueError("Unknown encrypted content type.")

        return {
            "success": True,
            "restored_path": str(output_path),
            "message": "Unlocked successfully."
        }

    finally:
        if os.path.exists(temp_payload):
            os.remove(temp_payload)
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

