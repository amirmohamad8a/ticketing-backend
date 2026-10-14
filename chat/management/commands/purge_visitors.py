from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from chat.retention import count_stale_visitors, purge_stale_visitors


class Command(BaseCommand):
    help = (
        "Delete visitors who have no tickets and have not been seen for the retention period "
        "(VISITOR_RETENTION_DAYS). Safe to run more than once."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Override VISITOR_RETENTION_DAYS for this run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only count the visitors that would be deleted.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        if days is not None and days < 1:
            raise CommandError("--days must be at least 1.")
        effective_days = settings.VISITOR_RETENTION_DAYS if days is None else days

        if options["dry_run"]:
            total = count_stale_visitors(days)
            self.stdout.write(
                f"{total} visitor(s) without tickets, not seen for {effective_days} days, "
                "would be deleted."
            )
            return

        deleted = purge_stale_visitors(days)
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted} visitor(s) without tickets, not seen for "
                f"{effective_days} days."
            )
        )
