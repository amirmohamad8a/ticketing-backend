from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from chat.retention import count_redactable_visitors, redact_stale_visitors


class Command(BaseCommand):
    help = (
        "Clear the name, phone and email of visitors whose conversations are all finished and "
        "who have not been seen for the retention period (VISITOR_RETENTION_DAYS). The visitor "
        "rows are kept, only the contact details are removed. Safe to run more than once."
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
            help="Only count the visitors whose contact details would be cleared.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        if days is not None and days < 1:
            raise CommandError("--days must be at least 1.")
        effective_days = settings.VISITOR_RETENTION_DAYS if days is None else days

        if options["dry_run"]:
            total = count_redactable_visitors(days)
            self.stdout.write(
                f"{total} visitor(s) with finished conversations, not seen for "
                f"{effective_days} days, would have their contact details cleared."
            )
            return

        redacted = redact_stale_visitors(days)
        self.stdout.write(
            self.style.SUCCESS(
                f"Cleared the contact details of {redacted} visitor(s) with finished "
                f"conversations, not seen for {effective_days} days."
            )
        )
