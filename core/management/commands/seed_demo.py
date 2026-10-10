from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from tickets.models import Comment, Ticket, TicketEvent

CUSTOMER_USERNAME = "demo_customer"
AGENT_USERNAME = "demo_agent"
DEMO_PASSWORD = "demo-ticketing-2026"

TICKETS = [
    {
        "title": "Cannot log in on the mobile app",
        "description": "The app rejects my password on my phone, but it works on the website.",
        "priority": Ticket.Priority.HIGH,
        "assigned": True,
        "path": [Ticket.Status.IN_PROGRESS],
        "comments": [
            ("customer", "I tried reinstalling the app and it did not help.", False),
            ("agent", "Thanks. I am checking the login logs for your account.", False),
            ("agent", "Stale session on the mobile client, not an account issue.", True),
        ],
    },
    {
        "title": "Invoice shows the wrong amount",
        "description": "My October invoice is higher than the price of my plan.",
        "priority": Ticket.Priority.MEDIUM,
        "assigned": False,
        "path": [],
        "comments": [
            ("customer", "Could someone confirm which plan I am being billed on?", False),
        ],
    },
    {
        "title": "Report export fails for large ranges",
        "description": "Exporting a report for a full year fails with a server error.",
        "priority": Ticket.Priority.URGENT,
        "assigned": True,
        "path": [Ticket.Status.IN_PROGRESS, Ticket.Status.WAITING_ON_CUSTOMER],
        "comments": [
            ("agent", "Which date range were you exporting when it failed?", False),
            ("agent", "Exports over 90 days probably hit the request timeout.", True),
        ],
    },
    {
        "title": "Add a dark mode to the dashboard",
        "description": "Please add a dark theme to the dashboard for night shifts.",
        "priority": Ticket.Priority.LOW,
        "assigned": True,
        "path": [Ticket.Status.IN_PROGRESS, Ticket.Status.RESOLVED],
        "comments": [
            ("agent", "Dark mode is live. You can switch it on in your settings.", False),
            ("customer", "Works great, thank you!", False),
        ],
    },
]


class Command(BaseCommand):
    help = "Create the demo users, tickets and comments. Safe to run more than once."

    @transaction.atomic
    def handle(self, *args, **options):
        customer = self._get_or_create_user(CUSTOMER_USERNAME, User.Role.CUSTOMER)
        agent = self._get_or_create_user(AGENT_USERNAME, User.Role.AGENT)
        authors = {"customer": customer, "agent": agent}
        new_tickets = sum(self._seed_ticket(spec, customer, agent, authors) for spec in TICKETS)
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready: {new_tickets} new ticket(s), "
                f"users {CUSTOMER_USERNAME} and {AGENT_USERNAME}."
            )
        )

    def _get_or_create_user(self, username, role):
        user, created = User.objects.get_or_create(
            username=username, defaults={"role": role, "email": ""}
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save(update_fields=["password"])
        return user

    def _seed_ticket(self, spec, customer, agent, authors):
        path = spec["path"]
        ticket, created = Ticket.all_objects.get_or_create(
            customer=customer,
            title=spec["title"],
            defaults={
                "description": spec["description"],
                "priority": spec["priority"],
                "status": path[-1] if path else Ticket.Status.OPEN,
                "assignee": agent if spec["assigned"] else None,
            },
        )
        if created:
            self._record_history(ticket, customer, agent, path)
        elif ticket.is_deleted:
            ticket.restore()
        for role, body, is_internal in spec["comments"]:
            Comment.objects.get_or_create(
                ticket=ticket,
                author=authors[role],
                body=body,
                defaults={"is_internal": is_internal},
            )
        return created

    def _record_history(self, ticket, customer, agent, path):
        entries = [(customer, "created", "", Ticket.Status.OPEN)]
        if ticket.assignee_id:
            entries.append((agent, "assignee", "", agent.username))
        previous = Ticket.Status.OPEN
        for status in path:
            entries.append((agent, "status", previous, status))
            previous = status
        for actor, field_changed, old_value, new_value in entries:
            TicketEvent.objects.create(
                ticket=ticket,
                actor=actor,
                field_changed=field_changed,
                old_value=old_value,
                new_value=new_value,
            )
