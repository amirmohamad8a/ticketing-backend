import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0002_visitor"),
        ("tickets", "0007_ticket_channel_site_visitor"),
    ]

    operations = [
        migrations.AddField(
            model_name="comment",
            name="kind",
            field=models.CharField(
                choices=[("message", "Message"), ("system", "System")],
                default="message",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="comment",
            name="client_msg_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="comment",
            name="visitor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="comments",
                to="chat.visitor",
            ),
        ),
        migrations.AddConstraint(
            model_name="comment",
            constraint=models.UniqueConstraint(
                fields=("ticket", "client_msg_id"),
                name="comment_unique_client_msg_id_per_ticket",
            ),
        ),
        migrations.AddConstraint(
            model_name="comment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("kind", "system"),
                    models.Q(("author__isnull", False), ("visitor__isnull", True)),
                    models.Q(("author__isnull", True), ("visitor__isnull", False)),
                    _connector="OR",
                ),
                name="comment_message_exactly_one_sender",
            ),
        ),
    ]
