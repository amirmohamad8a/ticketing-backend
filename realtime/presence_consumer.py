import json

from django.conf import settings

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from accounts.permissions import STAFF_ROLES
from realtime import presence
from realtime.consumers import (
    CLOSE_MESSAGE_TOO_BIG,
    CLOSE_RATE_LIMITED,
    CLOSE_UNAUTHENTICATED,
    CLOSE_UNSUPPORTED_DATA,
)
from realtime.limits import MessageRateLimiter

CLOSE_FORBIDDEN = 4403


class PresenceConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.limiter = None
        self.status = presence.STATUS_AVAILABLE

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        if user.role not in STAFF_ROLES:
            await self.close(code=CLOSE_FORBIDDEN)
            return
        self.user = user
        self.limiter = MessageRateLimiter(
            settings.WS_RATE_LIMIT_MESSAGES, settings.WS_RATE_LIMIT_WINDOW_SECONDS
        )
        await self.accept()
        await self._heartbeat()
        await self._send_state()

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
            await self._heartbeat()
            await self._send({"type": "pong", "status": self.status})
        elif message_type == "set_status":
            await self._set_status(content.get("status"))
        else:
            await self._send_error("unknown_type")

    async def _heartbeat(self):
        self.status = await sync_to_async(presence.heartbeat)(self.user.pk, self.status)

    async def _set_status(self, status):
        if status not in presence.STATUSES:
            await self._send_error("invalid_status")
            return
        await sync_to_async(presence.set_status)(self.user.pk, status)
        self.status = status
        await self._send_state()

    async def _send_state(self):
        await self._send({"type": "presence", "status": self.status})

    async def _send(self, payload):
        await self.send(text_data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    async def _send_error(self, code):
        await self._send({"type": "error", "code": code})
