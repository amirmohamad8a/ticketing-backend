from datetime import timedelta

from django.db import migrations, models
from django.db.models import ExpressionWrapper, F

from tickets.sla import first_response_minutes

PRIORITIES = ("low", "medium", "high", "urgent")


def backfill_due_dates(apps, schema_editor):
    Ticket = apps.get_model("tickets", "Ticket")
    for priority in PRIORITIES:
        Ticket.objects.filter(priority=priority).update(
            first_response_due_at=ExpressionWrapper(
                F("created_at") + timedelta(minutes=first_response_minutes(priority)),
                output_field=models.DateTimeField(),
            )
        )


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0013_tag"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="first_response_due_at",
            field=models.DateTimeField(blank=True, db_index=True, editable=False, null=True),
        ),
        migrations.RunPython(backfill_due_dates, migrations.RunPython.noop),
    ]
