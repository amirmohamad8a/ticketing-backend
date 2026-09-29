import logging
import smtplib

from django.core.mail import mailers

from notifications.emails import build_messages
from notifications.exceptions import ProviderError

logger = logging.getLogger(__name__)


def deliver(event):
    messages = build_messages(event)
    if not messages:
        logger.info("No recipients for event %s", event.id)
        return 0
    try:
        return mailers["default"].send_messages(messages)
    except (smtplib.SMTPException, OSError) as exc:
        raise ProviderError(str(exc)) from exc
