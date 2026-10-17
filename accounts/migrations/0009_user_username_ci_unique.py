from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ("accounts", "0008_userevent_actor_protect"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
                        "user_username_ci_unique ON accounts_user (LOWER(username));"
                    ),
                    reverse_sql=("DROP INDEX CONCURRENTLY IF EXISTS user_username_ci_unique;"),
                ),
            ],
            state_operations=[
                migrations.AddConstraint(
                    model_name="user",
                    constraint=models.UniqueConstraint(
                        Lower("username"), name="user_username_ci_unique"
                    ),
                ),
            ],
        ),
    ]
