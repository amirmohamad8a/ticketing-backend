from django.core.management.base import BaseCommand

from core.demo import AGENT_USERNAME, CUSTOMER_USERNAME, seed_demo_data


class Command(BaseCommand):
    help = (
        "Create the demo users, tickets, chat conversations, offline tickets, canned replies, "
        "tags and ratings. Safe to run more than once."
    )

    def handle(self, *args, **options):
        new_tickets = seed_demo_data()
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready: {new_tickets} new ticket(s), "
                f"users {CUSTOMER_USERNAME} and {AGENT_USERNAME}."
            )
        )
