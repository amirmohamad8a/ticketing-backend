from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from chat.models import Visitor
from chat.tokens import InvalidVisitorToken, decode_visitor_token, issue_visitor_token

LAST_SEEN_REFRESH_INTERVAL = timedelta(minutes=1)


@dataclass(frozen=True)
class VisitorSession:
    visitor: Visitor
    token: str


def _touch(visitor):
    now = timezone.now()
    if now - visitor.last_seen_at >= LAST_SEEN_REFRESH_INTERVAL:
        visitor.last_seen_at = now
        visitor.save(update_fields=["last_seen_at"])


def resolve_visitor(token):
    visitor_id, site_id = decode_visitor_token(token)
    try:
        visitor = Visitor.objects.select_related("site").get(pk=visitor_id, site_id=site_id)
    except Visitor.DoesNotExist:
        raise InvalidVisitorToken from None
    if not visitor.site.is_active:
        raise InvalidVisitorToken
    _touch(visitor)
    return visitor


def start_visitor_session(site, name="", phone="", email=""):
    visitor = Visitor.objects.create(site=site, name=name, phone=phone, email=email)
    return VisitorSession(visitor=visitor, token=issue_visitor_token(visitor))


def resume_visitor_session(token):
    visitor = resolve_visitor(token)
    return VisitorSession(visitor=visitor, token=issue_visitor_token(visitor))
