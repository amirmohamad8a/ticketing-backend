from django.core.management.base import BaseCommand

from core.demo import reset_demo_data


class Command(BaseCommand):
    help = (
        "Remove everything seed_demo created, plus everything created through the demo accounts "
        "and the demo site, then seed the demo data again. Use it before a recording."
    )

    def handle(self, *args, **options):
        new_tickets = reset_demo_data()
        self.stdout.write(
            self.style.SUCCESS(f"Demo data reset: {new_tickets} ticket(s) seeded from scratch.")
        )
