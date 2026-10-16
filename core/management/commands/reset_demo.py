from django.core.management.base import BaseCommand

from core.demo import ensure_demo_allowed, reset_demo_data


class Command(BaseCommand):
    help = (
        "Remove everything seed_demo created, plus everything created through the demo accounts "
        "and the demo site, then seed the demo data again. Use it before a recording. "
        "Refuses to run unless DEBUG is true or --force is given."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even when DEBUG is false.",
        )

    def handle(self, *args, **options):
        ensure_demo_allowed(options["force"])
        new_tickets = reset_demo_data()
        self.stdout.write(
            self.style.SUCCESS(f"Demo data reset: {new_tickets} ticket(s) seeded from scratch.")
        )
