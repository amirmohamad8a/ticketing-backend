from asgiref.sync import sync_to_async

from accounts.permissions import STAFF_ROLES
from chat import presence
from core.groups import user_group
from core.metrics import PRESENCE_ENDPOINT, socket_closed, socket_opened
from realtime.base_consumer import BaseRealtimeConsumer
from realtime.protocol import (
    CLIENT_PING,
    CLIENT_SET_STATUS,
    CLOSE_FORBIDDEN,
    CLOSE_UNAUTHENTICATED,
    ERROR_INVALID_STATUS,
    EVENT_PONG,
    EVENT_PRESENCE,
)

METRICS_CLIENT = "agent"


class PresenceConsumer(BaseRealtimeConsumer):
    message_handlers = {
        CLIENT_PING: "_handle_ping",
        CLIENT_SET_STATUS: "_handle_set_status",
    }

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
        self._start_limiter()
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

    async def _handle_ping(self, content):
        await self._heartbeat()
        await self._send({"type": EVENT_PONG, "status": self.status})

    async def _handle_set_status(self, content):
        await self._set_status(content.get("status"))

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
