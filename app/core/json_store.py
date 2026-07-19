import copy
import fcntl
import json
import os
import shutil
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, TypeVar


T = TypeVar("T")
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(path: str) -> threading.RLock:
    normalized = os.path.abspath(path)
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(normalized, threading.RLock())


@contextmanager
def _locked(path: str):
    lock = _thread_lock(path)
    lock_path = f"{path}.lock"
    Path(lock_path).parent.mkdir(parents=True, exist_ok=True)

    with lock:
        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_unlocked(path: str, default: T) -> T:
    if not os.path.exists(path):
        return copy.deepcopy(default)

    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_unlocked(path: str, data) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists():
        try:
            _read_unlocked(path, None)
            shutil.copy2(destination, f"{path}.bak")
        except (json.JSONDecodeError, OSError, TypeError):
            pass

    file_descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=str(destination.parent),
        text=True,
    )

    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary_path, path)

        directory_descriptor = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def load_json(path: str, default: T) -> T:
    with _locked(path):
        try:
            return _read_unlocked(path, default)
        except (json.JSONDecodeError, OSError, TypeError):
            backup_path = f"{path}.bak"
            try:
                recovered = _read_unlocked(backup_path, default)
                _write_unlocked(path, recovered)
                return recovered
            except (json.JSONDecodeError, OSError, TypeError):
                return copy.deepcopy(default)


def save_json(path: str, data) -> None:
    with _locked(path):
        _write_unlocked(path, data)


def update_json(path: str, default: T, mutator: Callable[[T], T | None]) -> T:
    with _locked(path):
        try:
            current = _read_unlocked(path, default)
        except (json.JSONDecodeError, OSError, TypeError):
            try:
                current = _read_unlocked(f"{path}.bak", default)
            except (json.JSONDecodeError, OSError, TypeError):
                current = copy.deepcopy(default)

        replacement = mutator(current)
        updated = current if replacement is None else replacement
        _write_unlocked(path, updated)
        return updated
