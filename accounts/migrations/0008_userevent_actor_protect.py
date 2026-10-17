import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_userevent_created_index"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userevent",
            name="actor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="user_events_made",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
