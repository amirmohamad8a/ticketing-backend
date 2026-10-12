from django.apps import AppConfig


class ChatConfig(AppConfig):
    name = "chat"

    def ready(self):
        from chat.widget import cors, schema  # noqa: F401
