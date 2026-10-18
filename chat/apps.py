from django.apps import AppConfig


class ChatConfig(AppConfig):
    name = "chat"

    def ready(self):
        from chat import signals  # noqa: F401
        from chat.widget import cors, schema  # noqa: F401
