from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0004_attachment"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="is_deleted",
            field=models.BooleanField(default=False),
        ),
    ]
