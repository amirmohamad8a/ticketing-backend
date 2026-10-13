import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_userevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="max_concurrent_chats",
            field=models.PositiveSmallIntegerField(
                default=5,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(50),
                ],
            ),
        ),
    ]
