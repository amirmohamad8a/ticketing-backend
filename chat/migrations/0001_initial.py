import django.core.validators
from django.db import migrations, models

import chat.models
import chat.validators


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Site",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=100)),
                (
                    "key",
                    models.CharField(
                        default=chat.models.generate_site_key,
                        editable=False,
                        max_length=64,
                        unique=True,
                    ),
                ),
                (
                    "allowed_origins",
                    models.JSONField(
                        blank=True,
                        default=list,
                        validators=[chat.validators.validate_origin_list],
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("greeting", models.CharField(blank=True, default="", max_length=500)),
                (
                    "primary_color",
                    models.CharField(
                        default="#2563eb",
                        max_length=7,
                        validators=[chat.validators.validate_hex_color],
                    ),
                ),
                (
                    "position",
                    models.CharField(
                        choices=[("bottom_right", "Bottom right"), ("bottom_left", "Bottom left")],
                        default="bottom_right",
                        max_length=20,
                    ),
                ),
                (
                    "offline_timeout_minutes",
                    models.PositiveSmallIntegerField(
                        default=5,
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(1440),
                        ],
                    ),
                ),
                ("require_name", models.BooleanField(default=False)),
                ("require_contact", models.BooleanField(default=False)),
            ],
            options={
                "ordering": ["id"],
            },
        ),
    ]
