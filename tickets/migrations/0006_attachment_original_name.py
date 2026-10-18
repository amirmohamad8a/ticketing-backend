import os

from django.db import migrations, models

import tickets.models


def fill_original_names(apps, schema_editor):
    Attachment = apps.get_model("tickets", "Attachment")
    rows = Attachment.objects.filter(original_name="").values_list("pk", "file")
    for pk, name in rows.iterator():
        Attachment.objects.filter(pk=pk).update(original_name=os.path.basename(name)[:255])


class Migration(migrations.Migration):

    dependencies = [
        ("tickets", "0005_ticket_soft_delete"),
    ]

    operations = [
        migrations.AddField(
            model_name="attachment",
            name="original_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AlterField(
            model_name="attachment",
            name="file",
            field=models.FileField(upload_to=tickets.models.attachment_upload_path),
        ),
        migrations.RunPython(fill_original_names, migrations.RunPython.noop),
    ]
