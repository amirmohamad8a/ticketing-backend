from django.db import migrations, models
from django.db.models import OuterRef, Subquery

STAFF_ROLES = ("agent", "admin")
FINISHED_STATUSES = ("resolved", "closed")


def backfill_metrics(apps, schema_editor):
    Ticket = apps.get_model("tickets", "Ticket")
    Comment = apps.get_model("tickets", "Comment")
    TicketEvent = apps.get_model("tickets", "TicketEvent")

    first_staff_reply = (
        Comment.objects.filter(
            ticket=OuterRef("pk"),
            kind="message",
            is_internal=False,
            author__role__in=STAFF_ROLES,
        )
        .order_by("created_at", "id")
        .values("created_at")[:1]
    )
    Ticket.objects.update(first_response_at=Subquery(first_staff_reply))

    last_resolution = (
        TicketEvent.objects.filter(
            ticket=OuterRef("pk"), field_changed="status", new_value="resolved"
        )
        .order_by("-created_at", "-id")
        .values("created_at")[:1]
    )
    Ticket.objects.filter(status__in=FINISHED_STATUSES).update(
        resolved_at=Subquery(last_resolution)
    )


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0014_ticket_first_response_due_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="first_response_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="resolved_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(backfill_metrics, migrations.RunPython.noop),
    ]
