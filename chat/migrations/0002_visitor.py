import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

import accounts.validators


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Visitor",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(blank=True, default="", max_length=100)),
                (
                    "phone",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=11,
                        validators=[accounts.validators.validate_iranian_mobile],
                    ),
                ),
                ("email", models.EmailField(blank=True, default="", max_length=254)),
                (
                    "last_seen_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "site",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="visitors",
                        to="chat.site",
                    ),
                ),
            ],
            options={
                "ordering": ["id"],
            },
        ),
    ]
