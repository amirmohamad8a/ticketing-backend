import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0002_visitor"),
        ("tickets", "0006_attachment_original_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="channel",
            field=models.CharField(
                choices=[
                    ("portal", "Portal"),
                    ("chat", "Chat"),
                    ("offline_form", "Offline form"),
                ],
                default="portal",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="site",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="tickets",
                to="chat.site",
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="visitor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="tickets",
                to="chat.visitor",
            ),
        ),
        migrations.AlterField(
            model_name="ticket",
            name="customer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="tickets",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="ticket",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("customer__isnull", False), ("visitor__isnull", True)),
                    models.Q(("customer__isnull", True), ("visitor__isnull", False)),
                    _connector="OR",
                ),
                name="ticket_exactly_one_owner",
            ),
        ),
    ]
