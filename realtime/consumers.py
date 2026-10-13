import json

from django.conf import settings

from channels.generic.websocket import AsyncWebsocketConsumer

from realtime.access import can_join_ticket
from realtime.groups import ticket_group
from realtime.limits import MessageRateLimiter

CLOSE_UNSUPPORTED_DATA = 1003
CLOSE_MESSAGE_TOO_BIG = 1009
CLOSE_UNAUTHENTICATED = 4401
CLOSE_RATE_LIMITED = 4429
MAX_JOINED_TICKETS = 50
MAX_ID = 2**63 - 1


def _is_valid_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_ID


class RealtimeConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.visitor = None
        self.limiter = None
        self.ticket_ids = set()

    async def connect(self):
        user = self.scope.get("user")
        visitor = self.scope.get("visitor")
        authenticated = user is not None and user.is_authenticated
        if not authenticated and visitor is None:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        self.user = user if authenticated else None
        self.visitor = visitor
        self.limiter = MessageRateLimiter(
            settings.WS_RATE_LIMIT_MESSAGES, settings.WS_RATE_LIMIT_WINDOW_SECONDS
        )
        await self.accept()

    async def disconnect(self, code):
        for ticket_id in self.ticket_ids:
            await self.channel_layer.group_discard(ticket_group(ticket_id), self.channel_name)
        self.ticket_ids.clear()

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
            await self._send_error("invalid_json")
            return
        if not isinstance(content, dict):
            await self._send_error("invalid_message")
            return
        message_type = content.get("type")
        if message_type == "ping":
            await self._send({"type": "pong"})
        elif message_type == "join":
            await self._join(content.get("ticket_id"))
        elif message_type == "leave":
            await self._leave(content.get("ticket_id"))
        else:
            await self._send_error("unknown_type")

    async def realtime_event(self, event):
        await self._send(event["payload"])

    async def _join(self, ticket_id):
        if not _is_valid_id(ticket_id):
            await self._send_error("invalid_ticket_id")
            return
        if ticket_id in self.ticket_ids:
            await self._send({"type": "joined", "ticket_id": ticket_id})
            return
        if len(self.ticket_ids) >= MAX_JOINED_TICKETS:
            await self._send_error("too_many_tickets", ticket_id)
            return
        if not await can_join_ticket(self.user, self.visitor, ticket_id):
            await self._send_error("not_found", ticket_id)
            return
        await self.channel_layer.group_add(ticket_group(ticket_id), self.channel_name)
        self.ticket_ids.add(ticket_id)
        await self._send({"type": "joined", "ticket_id": ticket_id})

    async def _leave(self, ticket_id):
        if not _is_valid_id(ticket_id):
            await self._send_error("invalid_ticket_id")
            return
        if ticket_id in self.ticket_ids:
            await self.channel_layer.group_discard(ticket_group(ticket_id), self.channel_name)
            self.ticket_ids.discard(ticket_id)
        await self._send({"type": "left", "ticket_id": ticket_id})

    async def _send(self, payload):
        await self.send(text_data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    async def _send_error(self, code, ticket_id=None):
        payload = {"type": "error", "code": code}
        if ticket_id is not None:
            payload["ticket_id"] = ticket_id
        await self._send(payload)
