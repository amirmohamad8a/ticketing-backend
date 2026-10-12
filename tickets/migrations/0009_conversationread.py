import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0002_visitor"),
        ("tickets", "0008_comment_chat_message"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ConversationRead",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("last_read_comment_id", models.PositiveBigIntegerField(default=0)),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reads",
                        to="tickets.ticket",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="conversation_reads",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "visitor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="conversation_reads",
                        to="chat.visitor",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("ticket", "user"),
                        name="conversationread_unique_ticket_user",
                    ),
                    models.UniqueConstraint(
                        fields=("ticket", "visitor"),
                        name="conversationread_unique_ticket_visitor",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("user__isnull", False), ("visitor__isnull", True)),
                            models.Q(("user__isnull", True), ("visitor__isnull", False)),
                            _connector="OR",
                        ),
                        name="conversationread_exactly_one_reader",
                    ),
                ],
            },
        ),
    ]
