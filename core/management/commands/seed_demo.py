from django.core.management.base import BaseCommand

from core.demo import AGENT_USERNAME, CUSTOMER_USERNAME, DEMO_PASSWORD, seed_demo_data


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
        self.stdout.write("")
        self.stdout.write("Demo logins (same password for both accounts):")
        self.stdout.write(f"  customer  {CUSTOMER_USERNAME} / {DEMO_PASSWORD}")
        self.stdout.write(f"  agent     {AGENT_USERNAME} / {DEMO_PASSWORD}")
