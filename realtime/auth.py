from urllib.parse import parse_qs

from django.contrib.auth.models import AnonymousUser

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware

from accounts.models import User
from chat.models import Visitor
from chat.widget.auth import origin_allowed_for_site
from core.tickets import redeem_ticket
from tickets.participants import Participant

TICKET_PARAM = "ticket"


def _query_param(scope, name):
    query = scope.get("query_string", b"").decode("latin-1")
    values = parse_qs(query).get(name)
    return values[0] if values else ""


def _header(scope, name):
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


@database_sync_to_async
def _get_user(user_id):
    return User.objects.filter(pk=user_id, is_active=True).first()


@database_sync_to_async
def _get_visitor(visitor_id):
    return (
        Visitor.objects.select_related("site").filter(pk=visitor_id, site__is_active=True).first()
    )


class TicketAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        scope["user"] = AnonymousUser()
        scope["visitor"] = None
        scope["participant"] = None
        token = _query_param(scope, TICKET_PARAM)
        if token:
            payload = await sync_to_async(redeem_ticket)(token)
            if payload is not None:
                await self._attach(scope, payload)
        return await super().__call__(scope, receive, send)

    async def _attach(self, scope, payload):
        user_id = payload.get("user_id")
        visitor_id = payload.get("visitor_id")
        if user_id is not None:
            user = await _get_user(user_id)
            if user is not None:
                scope["user"] = user
                scope["participant"] = Participant(user=user)
        elif visitor_id is not None:
            visitor = await _get_visitor(visitor_id)
            if visitor is None:
                return
            origin = _header(scope, b"origin")
            if origin_allowed_for_site(origin, visitor.site):
                scope["visitor"] = visitor
                scope["participant"] = Participant(visitor=visitor)
