import posixpath

from django.core.files.storage import default_storage

FILE_PREFIXES = ("attachments", "avatars")
_reference_sources = []


def register_file_reference_source(source):
    if source not in _reference_sources:
        _reference_sources.append(source)


def _walk(storage, directory):
    try:
        directories, files = storage.listdir(directory)
    except (FileNotFoundError, NotImplementedError):
        return
    for name in files:
        yield posixpath.join(directory, name)
    for name in directories:
        yield from _walk(storage, posixpath.join(directory, name))


def referenced_files():
    names = set()
    for source in _reference_sources:
        names.update(source())
    names.discard("")
    return names


def find_orphan_files(storage=None):
    storage = storage or default_storage
    referenced = referenced_files()
    orphans = []
    for prefix in FILE_PREFIXES:
        for name in _walk(storage, prefix):
            if name not in referenced:
                orphans.append(name)
    return sorted(orphans)
