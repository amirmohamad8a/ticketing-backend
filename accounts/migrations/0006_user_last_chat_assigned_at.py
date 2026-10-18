from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_user_max_concurrent_chats"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="last_chat_assigned_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]
