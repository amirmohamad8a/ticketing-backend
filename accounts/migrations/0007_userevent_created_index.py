from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("accounts", "0006_user_last_chat_assigned_at"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="userevent",
            index=models.Index(fields=["created_at", "id"], name="userevent_created_id_idx"),
        ),
    ]
