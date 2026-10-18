from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("tickets", "0016_ticketrating"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="ticket",
            index=models.Index(fields=["-created_at", "-id"], name="ticket_created_id_desc_idx"),
        ),
        AddIndexConcurrently(
            model_name="comment",
            index=models.Index(fields=["ticket", "id"], name="comment_ticket_id_idx"),
        ),
        AddIndexConcurrently(
            model_name="ticketevent",
            index=models.Index(fields=["created_at", "id"], name="ticketevent_created_id_idx"),
        ),
    ]
