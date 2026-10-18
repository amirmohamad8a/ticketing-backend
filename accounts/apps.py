from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"

    def ready(self):
        from accounts.files import avatar_files
        from core.orphans import register_file_reference_source

        register_file_reference_source(avatar_files)
