import json

from django.conf import settings

from channels.generic.websocket import AsyncWebsocketConsumer

from accounts.permissions import STAFF_ROLES
from core.metrics import TICKETS_ENDPOINT, socket_closed, socket_opened
from realtime.access import can_join_ticket
from realtime.events import publish_typing
from realtime.groups import AGENTS_QUEUE_GROUP, ticket_group, user_group
from realtime.limits import MessageRateLimiter, TypingThrottle
from realtime.protocol import (
    CLIENT_JOIN,
    CLIENT_LEAVE,
    CLIENT_PING,
    CLIENT_TYPING,
    CLOSE_FORBIDDEN,
    CLOSE_MESSAGE_TOO_BIG,
    CLOSE_RATE_LIMITED,
    CLOSE_UNAUTHENTICATED,
    CLOSE_UNSUPPORTED_DATA,
    ERROR_INVALID_JSON,
    ERROR_INVALID_MESSAGE,
    ERROR_INVALID_TICKET_ID,
    ERROR_NOT_FOUND,
    ERROR_NOT_JOINED,
    ERROR_TOO_MANY_TICKETS,
    ERROR_UNKNOWN_TYPE,
    EVENT_ERROR,
    EVENT_JOINED,
    EVENT_LEFT,
    EVENT_PONG,
)
from tickets.models import SenderType

MAX_JOINED_TICKETS = 50
MAX_ID = 2**63 - 1
SUPPORT_NAME = "Support"


def _is_valid_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_ID


def _display_name(user, is_staff):
    full_name = user.get_full_name()
    if full_name:
        return full_name
    return SUPPORT_NAME if is_staff else user.username


class RealtimeConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.visitor = None
        self.is_staff = False
        self.limiter = None
        self.typing = None
        self.identity = None
        self.sender_type = None
        self.sender_name = ""
        self.ticket_ids = set()
        self.metrics_client = None

    async def connect(self):
        user = self.scope.get("user")
        visitor = self.scope.get("visitor")
        authenticated = user is not None and user.is_authenticated
        if not authenticated and visitor is None:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        self.user = user if authenticated else None
        self.visitor = visitor
        self.is_staff = self.user is not None and self.user.role in STAFF_ROLES
        if self.user is not None:
            self.identity = f"user:{self.user.pk}"
            self.sender_type = SenderType.AGENT if self.is_staff else SenderType.CUSTOMER
            self.sender_name = _display_name(self.user, self.is_staff)
        else:
            self.identity = f"visitor:{self.visitor.pk}"
            self.sender_type = SenderType.VISITOR
            self.sender_name = self.visitor.name
        self.limiter = MessageRateLimiter(
            settings.WS_RATE_LIMIT_MESSAGES, settings.WS_RATE_LIMIT_WINDOW_SECONDS
        )
        self.typing = TypingThrottle(settings.WS_TYPING_THROTTLE_SECONDS)
        if self.user is not None:
            await self.channel_layer.group_add(user_group(self.user.pk), self.channel_name)
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
        if self.user is not None:
            await self.channel_layer.group_discard(user_group(self.user.pk), self.channel_name)
        if self.is_staff:
            await self.channel_layer.group_discard(AGENTS_QUEUE_GROUP, self.channel_name)
            self.is_staff = False

    async def receive(self, text_data=None, bytes_data=None):
        if text_data is None:
            await self.close(code=CLOSE_UNSUPPORTED_DATA)
            return
        if len(text_data.encode("utf-8")) > settings.WS_MAX_MESSAGE_BYTES:
            await self.close(code=CLOSE_MESSAGE_TOO_BIG)
            return
        if not self.limiter.allow():
            await self.close(code=CLOSE_RATE_LIMITED)
            return
        try:
            content = json.loads(text_data)
        except (ValueError, RecursionError):
            await self._send_error(ERROR_INVALID_JSON)
            return
        if not isinstance(content, dict):
            await self._send_error(ERROR_INVALID_MESSAGE)
            return
        message_type = content.get("type")
        if message_type == CLIENT_PING:
            await self._send({"type": EVENT_PONG})
        elif message_type == CLIENT_JOIN:
            await self._join(content.get("ticket_id"))
        elif message_type == CLIENT_LEAVE:
            await self._leave(content.get("ticket_id"))
        elif message_type == CLIENT_TYPING:
            await self._typing(content.get("ticket_id"), content.get("is_typing"))
        else:
            await self._send_error(ERROR_UNKNOWN_TYPE)

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

    async def realtime_close(self, event):
        await self.close(code=CLOSE_FORBIDDEN)

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
        if not await can_join_ticket(self.user, self.visitor, ticket_id):
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

    async def _send(self, payload):
        await self.send(text_data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    async def _send_error(self, code, ticket_id=None):
        payload = {"type": EVENT_ERROR, "code": code}
        if ticket_id is not None:
            payload["ticket_id"] = ticket_id
        await self._send(payload)
