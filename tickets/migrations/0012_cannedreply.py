import django.core.validators
from django.db import migrations, models

import tickets.validators


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0011_search_indexes"),
    ]

    operations = [
        migrations.CreateModel(
            name="CannedReply",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(max_length=100)),
                (
                    "body",
                    models.TextField(validators=[django.core.validators.MaxLengthValidator(4000)]),
                ),
                (
                    "shortcut",
                    models.CharField(
                        max_length=32,
                        unique=True,
                        validators=[tickets.validators.validate_shortcut],
                    ),
                ),
            ],
            options={
                "ordering": ["shortcut", "id"],
            },
        ),
    ]
