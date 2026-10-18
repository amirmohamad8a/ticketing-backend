import json

from django.conf import settings

from channels.generic.websocket import AsyncWebsocketConsumer

from realtime.limits import MessageRateLimiter
from realtime.protocol import (
    CLOSE_FORBIDDEN,
    CLOSE_MESSAGE_TOO_BIG,
    CLOSE_RATE_LIMITED,
    CLOSE_UNSUPPORTED_DATA,
    ERROR_INVALID_JSON,
    ERROR_INVALID_MESSAGE,
    ERROR_UNKNOWN_TYPE,
    EVENT_ERROR,
)


class BaseRealtimeConsumer(AsyncWebsocketConsumer):
    message_handlers = {}

    def _start_limiter(self):
        self.limiter = MessageRateLimiter(
            settings.WS_RATE_LIMIT_MESSAGES, settings.WS_RATE_LIMIT_WINDOW_SECONDS
        )
        return self.limiter

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
        handler = self.message_handlers.get(content.get("type"))
        if handler is None:
            await self._send_error(ERROR_UNKNOWN_TYPE)
            return
        await getattr(self, handler)(content)

    async def realtime_close(self, event):
        await self.close(code=CLOSE_FORBIDDEN)

    async def _send(self, payload):
        await self.send(text_data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    async def _send_error(self, code, ticket_id=None):
        payload = {"type": EVENT_ERROR, "code": code}
        if ticket_id is not None:
            payload["ticket_id"] = ticket_id
        await self._send(payload)
