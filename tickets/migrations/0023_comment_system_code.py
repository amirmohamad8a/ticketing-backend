from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0022_attachment_is_internal"),
    ]

    operations = [
        migrations.AddField(
            model_name="comment",
            name="system_code",
            field=models.CharField(
                blank=True,
                choices=[("offline_notice", "Offline notice")],
                default="",
                max_length=32,
            ),
        ),
    ]
