"""Shared test data and setup helpers."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from io import BytesIO

from django.utils import timezone


def storage_listing(files, path):
    prefix = path + "/" if path else ""
    names = [name[len(prefix) :] for name in files if name.startswith(prefix)]
    return sorted({name.split("/")[0] for name in names if "/" in name}), [name for name in names if "/" not in name]


class StubOverwriteStorage:
    """In-memory storage that overwrites existing names, like object storage does."""

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self._files: dict[str, bytes] = dict(files or {})
        self.saved: list[str] = []
        self.deleted: list[str] = []
        self.opened: list[str] = []

    def exists(self, path: str) -> bool:
        return path in self._files

    def get_modified_time(self, path: str):
        return timezone.now() - timedelta(days=8)

    def get_created_time(self, path: str):
        raise NotImplementedError

    def size(self, path: str) -> int:
        return len(self._files[path])

    def listdir(self, path: str) -> tuple[list[str], list[str]]:
        return storage_listing(self._files, path)

    def save(self, name: str, content: BytesIO) -> str:
        self.saved.append(name)
        self._files[name] = content.read()
        return name

    def delete(self, path: str) -> None:
        self.deleted.append(path)
        self._files.pop(path, None)

    @contextmanager
    def open(self, name: str, _mode: str) -> Iterator[BytesIO]:
        self.opened.append(name)
        yield BytesIO(self._files[name])

    def staged(self) -> list[str]:
        return [name for name in self._files if ".django-cast-refresh-" in name]
