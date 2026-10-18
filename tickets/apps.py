from django.apps import AppConfig


class TicketsConfig(AppConfig):
    name = "tickets"

    def ready(self):
        from core.orphans import register_file_reference_source
        from tickets import signals  # noqa: F401
        from tickets.files import attachment_files

        register_file_reference_source(attachment_files)
