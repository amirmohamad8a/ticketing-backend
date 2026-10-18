from django.utils.translation import gettext_lazy as _

from rest_framework import status

from core.errors import DomainError


class ConversationClosed(DomainError):
    status_code = status.HTTP_409_CONFLICT
    code = "conversation_closed"
    default_code = "conversation_closed"
    default_message = _("This conversation is closed.")
