import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import Signal, receiver

from accounts.signals import user_deactivated, user_demoted
from core.events import ATTACHMENT_EVENT_TYPE, publish
from tickets.models import Attachment

logger = logging.getLogger(__name__)

tickets_released = Signal()


@receiver(user_deactivated)
@receiver(user_demoted)
def release_user_tickets(sender, user, actor=None, **kwargs):
    from tickets.assignment import release_tickets

    release_tickets(user, actor)


def _delete_file(storage, name):
    try:
        storage.delete(name)
    except Exception:
        logger.warning(
            "Could not delete an attachment file",
            extra={"attachment_name": name},
            exc_info=True,
        )


@receiver(post_save, sender=Attachment)
def publish_attachment_created(sender, instance, created, **kwargs):
    if not created:
        return
    comment = instance.comment
    ticket_id = instance.ticket_id if comment is None else comment.ticket_id
    is_internal = instance.is_internal or (comment is not None and comment.is_internal)
    publish(
        ATTACHMENT_EVENT_TYPE,
        instance.pk,
        ticket_id,
        {
            "attachment_id": instance.pk,
            "comment_id": instance.comment_id,
            "is_internal": is_internal,
        },
        staff_only=is_internal,
    )


@receiver(post_delete, sender=Attachment)
def delete_attachment_file(sender, instance, **kwargs):
    if not instance.file:
        return
    name = instance.file.name
    if not name:
        return
    storage = instance.file.storage
    transaction.on_commit(lambda: _delete_file(storage, name))
