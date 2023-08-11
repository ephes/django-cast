import os
from collections.abc import Iterable

from django.core.files.storage import Storage


def storage_walk_paths(storage: Storage, cur_dir: str = "") -> Iterable[str]:
    dirs, files = storage.listdir(cur_dir)
    for directory in dirs:
        new_dir = os.path.join(cur_dir, directory)
        for path in storage_walk_paths(storage, cur_dir=new_dir):
            yield path
    for file_name in files:
        path = os.path.join(cur_dir, file_name)
        yield path
