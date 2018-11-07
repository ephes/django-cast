import os


def storage_walk_paths(storage, cur_dir=""):
    dirs, files = storage.listdir(cur_dir)
    for directory in dirs:
        new_dir = os.path.join(cur_dir, directory)
        for path in storage_walk_paths(storage, cur_dir=new_dir):
            yield path
    for fname in files:
        path = os.path.join(cur_dir, fname)
        yield path
