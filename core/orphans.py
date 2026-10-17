import posixpath

from django.core.files.storage import default_storage

FILE_PREFIXES = ("attachments", "avatars")


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
    from accounts.models import User
    from tickets.models import Attachment

    names = set(Attachment.objects.values_list("file", flat=True))
    names.update(User.objects.exclude(avatar="").values_list("avatar", flat=True))
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
