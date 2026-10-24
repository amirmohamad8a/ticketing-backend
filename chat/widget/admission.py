from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import NotFound

from chat.conversations import (
    find_replayed_start,
    open_conversation,
    replay_session,
    start_or_replay,
)
from chat.models import Site
from chat.tokens import issue_visitor_token
from chat.widget.auth import ensure_origin_allowed
from chat.widget.limits import ensure_site_capacity
from chat.widget.pow import verify_solution
from core.errors import DomainValidationError


def find_site(key, field):
    if not key:
        raise DomainValidationError({field: [_("This field is required.")]})
    site = Site.objects.filter(key=key, is_active=True).first()
    if site is None:
        raise NotFound
    return site


def check_required_fields(site, data):
    errors = {}
    if site.require_name and not data.get("name"):
        errors["name"] = _("This field is required.")
    if site.require_contact and not (data.get("phone") or data.get("email")):
        errors["contact"] = _("A phone number or an email is required.")
    if errors:
        raise DomainValidationError(errors)


def admit_new_visitor(site, data):
    check_required_fields(site, data)
    verify_solution(site, data.get("pow_challenge"), data.get("pow_nonce"))
    ensure_site_capacity(site)
    return site


def start_new_conversation(request, data):
    site = find_site(data.get("site_key"), "site_key")
    ensure_origin_allowed(request, site)
    client_msg_id = data.get("client_msg_id") or None
    replay = find_replayed_start(site, client_msg_id, data["body"])
    if replay is not None:
        session = replay_session(replay)
        return session.visitor, session.token, replay.ticket, replay, False
    admit_new_visitor(site, data)
    session, ticket, comment, created = start_or_replay(
        site,
        data["body"],
        name=data.get("name") or "",
        phone=data.get("phone") or "",
        email=data.get("email") or "",
        client_msg_id=client_msg_id,
    )
    return session.visitor, session.token, ticket, comment, created


def continue_conversation(visitor, data, request):
    ensure_origin_allowed(request, visitor.site)
    ticket, comment, created = open_conversation(
        visitor, data["body"], data.get("client_msg_id") or None
    )
    return visitor, issue_visitor_token(visitor), ticket, comment, created
