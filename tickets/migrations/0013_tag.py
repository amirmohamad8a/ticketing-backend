import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0012_cannedreply"),
    ]

    operations = [
        migrations.CreateModel(
            name="Tag",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=50)),
                (
                    "color",
                    models.CharField(
                        choices=[
                            ("gray", "Gray"),
                            ("red", "Red"),
                            ("orange", "Orange"),
                            ("yellow", "Yellow"),
                            ("green", "Green"),
                            ("teal", "Teal"),
                            ("blue", "Blue"),
                            ("purple", "Purple"),
                            ("pink", "Pink"),
                        ],
                        default="gray",
                        max_length=10,
                    ),
                ),
            ],
            options={
                "ordering": ["name", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"),
                        name="tag_unique_name_ci",
                    )
                ],
            },
        ),
        migrations.AddField(
            model_name="ticket",
            name="tags",
            field=models.ManyToManyField(blank=True, related_name="tickets", to="tickets.tag"),
        ),
    ]
