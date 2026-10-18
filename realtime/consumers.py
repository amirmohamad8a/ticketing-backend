from django.conf import settings

from core.events import publish_typing
from core.groups import AGENTS_QUEUE_GROUP, ticket_group, user_group
from core.metrics import TICKETS_ENDPOINT, socket_closed, socket_opened
from realtime.access import can_join_ticket
from realtime.base_consumer import BaseRealtimeConsumer
from realtime.limits import TypingThrottle
from realtime.protocol import (
    CLIENT_JOIN,
    CLIENT_LEAVE,
    CLIENT_PING,
    CLIENT_TYPING,
    CLOSE_UNAUTHENTICATED,
    ERROR_INVALID_MESSAGE,
    ERROR_INVALID_TICKET_ID,
    ERROR_NOT_FOUND,
    ERROR_NOT_JOINED,
    ERROR_TOO_MANY_TICKETS,
    EVENT_JOINED,
    EVENT_LEFT,
    EVENT_PONG,
)

MAX_JOINED_TICKETS = 50
MAX_ID = 2**63 - 1


def _is_valid_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_ID


class RealtimeConsumer(BaseRealtimeConsumer):
    message_handlers = {
        CLIENT_PING: "_handle_ping",
        CLIENT_JOIN: "_handle_join",
        CLIENT_LEAVE: "_handle_leave",
        CLIENT_TYPING: "_handle_typing",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.participant = None
        self.is_staff = False
        self.limiter = None
        self.typing = None
        self.identity = None
        self.sender_type = None
        self.sender_name = ""
        self.ticket_ids = set()
        self.metrics_client = None

    async def connect(self):
        participant = self.scope.get("participant")
        if participant is None:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        self.participant = participant
        self.is_staff = participant.is_staff
        self.identity = participant.socket_identity
        self.sender_type = participant.sender_type
        self.sender_name = participant.display_name
        self._start_limiter()
        self.typing = TypingThrottle(settings.WS_TYPING_THROTTLE_SECONDS)
        if not self.participant.is_visitor:
            await self.channel_layer.group_add(
                user_group(self.participant.user.pk), self.channel_name
            )
        if self.is_staff:
            await self.channel_layer.group_add(AGENTS_QUEUE_GROUP, self.channel_name)
        await self.accept()
        socket_opened(TICKETS_ENDPOINT, self.sender_type)
        self.metrics_client = self.sender_type

    async def disconnect(self, code):
        if self.metrics_client is not None:
            socket_closed(TICKETS_ENDPOINT, self.metrics_client)
            self.metrics_client = None
        if self.typing is not None:
            for ticket_id in self.typing.active_tickets():
                await self._relay_typing(ticket_id, False)
        for ticket_id in self.ticket_ids:
            await self.channel_layer.group_discard(ticket_group(ticket_id), self.channel_name)
        self.ticket_ids.clear()
        if not self.participant.is_visitor:
            await self.channel_layer.group_discard(
                user_group(self.participant.user.pk), self.channel_name
            )
        if self.is_staff:
            await self.channel_layer.group_discard(AGENTS_QUEUE_GROUP, self.channel_name)
            self.is_staff = False

    async def realtime_event(self, event):
        if self.is_staff:
            if event["group"] != AGENTS_QUEUE_GROUP:
                return
        elif event["staff_only"]:
            return
        await self._send(event["payload"])

    async def realtime_typing(self, event):
        if event["sender"] == self.identity:
            return
        await self._send(event["payload"])

    async def _handle_ping(self, content):
        await self._send({"type": EVENT_PONG})

    async def _handle_join(self, content):
        await self._join(content.get("ticket_id"))

    async def _handle_leave(self, content):
        await self._leave(content.get("ticket_id"))

    async def _handle_typing(self, content):
        await self._typing(content.get("ticket_id"), content.get("is_typing"))

    async def _join(self, ticket_id):
        if not _is_valid_id(ticket_id):
            await self._send_error(ERROR_INVALID_TICKET_ID)
            return
        if ticket_id in self.ticket_ids:
            await self._send({"type": EVENT_JOINED, "ticket_id": ticket_id})
            return
        if len(self.ticket_ids) >= MAX_JOINED_TICKETS:
            await self._send_error(ERROR_TOO_MANY_TICKETS, ticket_id)
            return
        if not await can_join_ticket(self.participant, ticket_id):
            await self._send_error(ERROR_NOT_FOUND, ticket_id)
            return
        await self.channel_layer.group_add(ticket_group(ticket_id), self.channel_name)
        self.ticket_ids.add(ticket_id)
        await self._send({"type": EVENT_JOINED, "ticket_id": ticket_id})

    async def _leave(self, ticket_id):
        if not _is_valid_id(ticket_id):
            await self._send_error(ERROR_INVALID_TICKET_ID)
            return
        if ticket_id in self.ticket_ids:
            if self.typing.is_typing(ticket_id):
                await self._relay_typing(ticket_id, False)
            self.typing.clear(ticket_id)
            await self.channel_layer.group_discard(ticket_group(ticket_id), self.channel_name)
            self.ticket_ids.discard(ticket_id)
        await self._send({"type": EVENT_LEFT, "ticket_id": ticket_id})

    async def _typing(self, ticket_id, is_typing):
        if not _is_valid_id(ticket_id):
            await self._send_error(ERROR_INVALID_TICKET_ID)
            return
        if not isinstance(is_typing, bool):
            await self._send_error(ERROR_INVALID_MESSAGE, ticket_id)
            return
        if ticket_id not in self.ticket_ids:
            await self._send_error(ERROR_NOT_JOINED, ticket_id)
            return
        if self.typing.allow(ticket_id, is_typing):
            await self._relay_typing(ticket_id, is_typing)

    async def _relay_typing(self, ticket_id, is_typing):
        await publish_typing(
            ticket_id, is_typing, self.identity, self.sender_type, self.sender_name
        )
