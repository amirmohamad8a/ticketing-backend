import json

from django.conf import settings

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from accounts.permissions import STAFF_ROLES
from core.metrics import PRESENCE_ENDPOINT, socket_closed, socket_opened
from realtime import presence
from realtime.groups import user_group
from realtime.limits import MessageRateLimiter
from realtime.protocol import (
    CLIENT_PING,
    CLIENT_SET_STATUS,
    CLOSE_FORBIDDEN,
    CLOSE_MESSAGE_TOO_BIG,
    CLOSE_RATE_LIMITED,
    CLOSE_UNAUTHENTICATED,
    CLOSE_UNSUPPORTED_DATA,
    ERROR_INVALID_JSON,
    ERROR_INVALID_MESSAGE,
    ERROR_INVALID_STATUS,
    ERROR_UNKNOWN_TYPE,
    EVENT_ERROR,
    EVENT_PONG,
    EVENT_PRESENCE,
)

METRICS_CLIENT = "agent"


class PresenceConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.limiter = None
        self.status = presence.STATUS_AVAILABLE
        self.counted = False

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
        await self.channel_layer.group_add(user_group(user.pk), self.channel_name)
        await self.accept()
        socket_opened(PRESENCE_ENDPOINT, METRICS_CLIENT)
        self.counted = True
        await self._heartbeat()
        await self._send_state()

    async def disconnect(self, code):
        if self.counted:
            socket_closed(PRESENCE_ENDPOINT, METRICS_CLIENT)
            self.counted = False
        if self.user is not None:
            await self.channel_layer.group_discard(user_group(self.user.pk), self.channel_name)

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
            await self._heartbeat()
            await self._send({"type": EVENT_PONG, "status": self.status})
        elif message_type == CLIENT_SET_STATUS:
            await self._set_status(content.get("status"))
        else:
            await self._send_error(ERROR_UNKNOWN_TYPE)

    async def realtime_close(self, event):
        await self.close(code=CLOSE_FORBIDDEN)

    async def _heartbeat(self):
        self.status = await sync_to_async(presence.heartbeat)(self.user.pk, self.status)

    async def _set_status(self, status):
        if status not in presence.STATUSES:
            await self._send_error(ERROR_INVALID_STATUS)
            return
        await sync_to_async(presence.set_status)(self.user.pk, status)
        self.status = status
        await self._send_state()

    async def _send_state(self):
        await self._send({"type": EVENT_PRESENCE, "status": self.status})

    async def _send(self, payload):
        await self.send(text_data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    async def _send_error(self, code):
        await self._send({"type": EVENT_ERROR, "code": code})
