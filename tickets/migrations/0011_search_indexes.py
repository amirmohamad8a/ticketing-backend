import django.contrib.postgres.indexes
import django.contrib.postgres.search
from django.db import migrations

import core.search


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0010_alter_comment_author_protect"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="ticket",
            index=django.contrib.postgres.indexes.GinIndex(
                django.contrib.postgres.search.SearchVector(
                    core.search.NormalizedText("title"),
                    core.search.NormalizedText("description"),
                    config="simple",
                ),
                name="ticket_search_gin",
            ),
        ),
        migrations.AddIndex(
            model_name="comment",
            index=django.contrib.postgres.indexes.GinIndex(
                django.contrib.postgres.search.SearchVector(
                    core.search.NormalizedText("body"),
                    config="simple",
                ),
                name="comment_search_gin",
            ),
        ),
    ]
