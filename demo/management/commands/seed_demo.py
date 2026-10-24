from django.core.management.base import BaseCommand

from demo.demo import (
    ADMIN_USERNAME,
    AGENT_USERNAME,
    CUSTOMER_USERNAME,
    DEMO_PASSWORD,
    ensure_demo_allowed,
    seed_demo_data,
)


class Command(BaseCommand):
    help = (
        "Create the demo users, tickets, chat conversations, offline tickets, canned replies, "
        "tags and ratings. Safe to run more than once. Refuses to run unless DEBUG is true "
        "or --force is given."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even when DEBUG is false.",
        )

    def handle(self, *args, **options):
        ensure_demo_allowed(options["force"])
        new_tickets = seed_demo_data()
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready: {new_tickets} new ticket(s), "
                f"users {CUSTOMER_USERNAME}, {AGENT_USERNAME} and {ADMIN_USERNAME}."
            )
        )
        self.stdout.write("")
        self.stdout.write("Demo logins (same password for every account):")
        self.stdout.write(f"  customer  {CUSTOMER_USERNAME} / {DEMO_PASSWORD}")
        self.stdout.write(f"  agent     {AGENT_USERNAME} / {DEMO_PASSWORD}")
        self.stdout.write(f"  admin     {ADMIN_USERNAME} / {DEMO_PASSWORD}")
