from django.conf import settings
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("chat", "0002_visitor"),
        ("tickets", "0018_ticketevent_actor_protect"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                condition=models.Q(
                    ("is_deleted", False),
                    models.Q(("status__in", ["resolved", "closed"]), _negated=True),
                ),
                fields=["channel", "assignee", "status"],
                name="ticket_chat_unfinished_idx",
            ),
        ),
        AddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                condition=models.Q(
                    ("assignee__isnull", True),
                    ("is_deleted", False),
                    models.Q(("status__in", ["resolved", "closed"]), _negated=True),
                ),
                fields=["assignee", "status"],
                name="ticket_unassigned_unfin_idx",
            ),
        ),
    ]
