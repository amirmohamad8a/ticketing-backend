from django.core.management.base import BaseCommand

from core.orphans import find_orphan_files


class Command(BaseCommand):
    help = (
        "List files under attachments/ and avatars/ that no Attachment or User row references. "
        "Reports only; it never deletes anything."
    )

    def handle(self, *args, **options):
        orphans = find_orphan_files()
        for name in orphans:
            self.stdout.write(name)
        self.stdout.write(
            self.style.WARNING(f"{len(orphans)} orphan file(s) found.")
            if orphans
            else self.style.SUCCESS("No orphan files found.")
        )
