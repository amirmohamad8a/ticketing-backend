import logging

from django.db import transaction

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from realtime.groups import AGENTS_QUEUE_GROUP, ticket_group

logger = logging.getLogger(__name__)

CHANNEL_EVENT_TYPE = "realtime.event"


async def _send_to_groups(layer, payload, staff_only):
    for group in (ticket_group(payload["ticket_id"]), AGENTS_QUEUE_GROUP):
        message = {
            "type": CHANNEL_EVENT_TYPE,
            "group": group,
            "staff_only": staff_only,
            "payload": payload,
        }
        try:
            await layer.group_send(group, message)
        except Exception:
            logger.exception(
                "Failed to publish a realtime event",
                extra={"group": group, "event_type": payload["type"], "event_id": payload["id"]},
            )


def _deliver(payload, staff_only):
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(_send_to_groups)(layer, payload, staff_only)


def publish(event_type, event_id, ticket_id, data, staff_only=False):
    payload = {"type": event_type, "id": event_id, "ticket_id": ticket_id, "data": data}
    transaction.on_commit(lambda: _deliver(payload, staff_only), robust=True)
