import logging

from django.db import transaction

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from realtime.groups import AGENTS_QUEUE_GROUP, ticket_group, user_group

logger = logging.getLogger(__name__)

CHANNEL_EVENT_TYPE = "realtime.event"
CHANNEL_TYPING_TYPE = "realtime.typing"
CHANNEL_CLOSE_TYPE = "realtime.close"
TYPING_EVENT_TYPE = "typing"


async def _send_to_groups(layer, payload, staff_only, public_payload=None):
    for group in (ticket_group(payload["ticket_id"]), AGENTS_QUEUE_GROUP):
        message = {
            "type": CHANNEL_EVENT_TYPE,
            "group": group,
            "staff_only": staff_only,
            "payload": payload,
            "public_payload": public_payload or payload,
        }
        try:
            await layer.group_send(group, message)
        except Exception:
            logger.exception(
                "Failed to publish a realtime event",
                extra={"group": group, "event_type": payload["type"], "event_id": payload["id"]},
            )


def _deliver(payload, staff_only, public_payload=None):
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(_send_to_groups)(layer, payload, staff_only, public_payload)


def _build_payload(event_type, event_id, ticket_id, data):
    return {"type": event_type, "id": event_id, "ticket_id": ticket_id, "data": data}


def publish(event_type, event_id, ticket_id, data, staff_only=False, public_data=None):
    payload = _build_payload(event_type, event_id, ticket_id, data)
    public_payload = None
    if public_data is not None:
        public_payload = _build_payload(event_type, event_id, ticket_id, public_data)
    transaction.on_commit(lambda: _deliver(payload, staff_only, public_payload), robust=True)


async def _send_close(layer, user_id):
    try:
        await layer.group_send(user_group(user_id), {"type": CHANNEL_CLOSE_TYPE})
    except Exception:
        logger.exception(
            "Failed to close the sockets of a user",
            extra={"user_id": user_id, "event_type": CHANNEL_CLOSE_TYPE},
        )


def _deliver_close(user_id):
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(_send_close)(layer, user_id)


def close_user_sockets(user_id):
    transaction.on_commit(lambda: _deliver_close(user_id), robust=True)


async def publish_typing(ticket_id, is_typing, sender_key, sender_type, sender_name):
    layer = get_channel_layer()
    if layer is None:
        return
    message = {
        "type": CHANNEL_TYPING_TYPE,
        "sender": sender_key,
        "payload": {
            "type": TYPING_EVENT_TYPE,
            "ticket_id": ticket_id,
            "is_typing": is_typing,
            "sender_type": sender_type,
            "sender_name": sender_name,
        },
    }
    try:
        await layer.group_send(ticket_group(ticket_id), message)
    except Exception:
        logger.exception(
            "Failed to publish a typing event",
            extra={"ticket_id": ticket_id, "event_type": TYPING_EVENT_TYPE},
        )
