from types import SimpleNamespace

from django.core import signing
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from chat.models import Site
from chat.tokens import issue_visitor_token
from core.downloads import DOWNLOAD_SALT
from core.tests import read_streaming_body
from core.tests.factories import (
    AdminFactory,
    AgentFactory,
    AttachmentFactory,
    CommentFactory,
    SiteFactory,
    TicketFactory,
    UserFactory,
    VisitorFactory,
)

ROLES = ("unauthenticated", "customer", "other_customer", "agent", "admin")
STATES = ("owner", "other_visitor", "bad_origin", "no_origin", "no_token", "invalid_token")
ORIGIN = "https://example.com"
EVIL_ORIGIN = "https://evil.example"


def _cases(table, keys):
    return [
        (name, key, statuses[index])
        for name, statuses in table.items()
        for index, key in enumerate(keys)
    ]


def _consume(response):
    if response.streaming:
        read_streaming_body(response)


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def people(db):
    return {
        "customer": UserFactory(),
        "other_customer": UserFactory(),
        "agent": AgentFactory(),
        "admin": AdminFactory(),
    }


def _client_for_role(role, people):
    client = APIClient()
    if role != "unauthenticated":
        refresh = RefreshToken.for_user(people[role])
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


STAFF_CALLS = {
    "stats": ("get", "/api/stats/"),
    "audit": ("get", "/api/audit/"),
    "agents": ("get", "/api/agents/"),
    "agents_online": ("get", "/api/agents/online/"),
    "export": ("get", "/api/tickets/export/"),
    "ws_ticket": ("post", "/api/ws/ticket/"),
}
STAFF_STATUSES = {
    "stats": (401, 403, 403, 200, 200),
    "audit": (401, 403, 403, 403, 200),
    "agents": (401, 403, 403, 200, 200),
    "agents_online": (401, 403, 403, 200, 200),
    "export": (401, 403, 403, 200, 200),
    "ws_ticket": (401, 200, 200, 200, 200),
}


@pytest.mark.parametrize("route,role,expected", _cases(STAFF_STATUSES, ROLES))
def test_staff_and_utility_routes(route, role, expected, people):
    method, url = STAFF_CALLS[route]
    client = _client_for_role(role, people)
    response = client.get(url) if method == "get" else client.post(url)
    assert response.status_code == expected
    _consume(response)


TICKET_CALLS = {
    "messages": ("get", "/api/tickets/{id}/messages/"),
    "comments": ("get", "/api/tickets/{id}/comments/"),
    "events": ("get", "/api/tickets/{id}/events/"),
    "read": ("post", "/api/tickets/{id}/read/"),
    "claim": ("post", "/api/tickets/{id}/claim/"),
}
TICKET_STATUSES = {
    "messages": (401, 200, 404, 200, 200),
    "comments": (401, 200, 404, 200, 200),
    "events": (401, 200, 404, 200, 200),
    "read": (401, 200, 404, 200, 200),
    "claim": (401, 403, 403, 200, 200),
}


@pytest.mark.parametrize("route,role,expected", _cases(TICKET_STATUSES, ROLES))
def test_ticket_sub_routes(route, role, expected, people):
    ticket = TicketFactory(customer=people["customer"])
    method, template = TICKET_CALLS[route]
    url = template.format(id=ticket.id)
    client = _client_for_role(role, people)
    if method == "get":
        response = client.get(url)
    else:
        response = client.post(url, {}, format="json")
    assert response.status_code == expected


SEARCH_CASES = [
    ("unauthenticated", "confidentialnote", 401, False),
    ("customer", "confidentialnote", 200, False),
    ("other_customer", "confidentialnote", 200, False),
    ("agent", "confidentialnote", 200, True),
    ("admin", "confidentialnote", 200, True),
    ("unauthenticated", "visibleword", 401, False),
    ("customer", "visibleword", 200, True),
    ("other_customer", "visibleword", 200, False),
    ("agent", "visibleword", 200, True),
    ("admin", "visibleword", 200, True),
]


@pytest.mark.parametrize("role,term,expected_status,visible", SEARCH_CASES)
def test_search_never_leaks_internal_notes_or_other_customers_tickets(
    role, term, expected_status, visible, people
):
    ticket = TicketFactory(customer=people["customer"])
    CommentFactory(ticket=ticket, author=people["agent"], body="confidentialnote", is_internal=True)
    CommentFactory(ticket=ticket, author=people["agent"], body="visibleword")
    client = _client_for_role(role, people)
    response = client.get("/api/tickets/", {"search": term})
    assert response.status_code == expected_status
    if expected_status == 200:
        ids = {row["id"] for row in response.data["results"]}
        assert (ticket.id in ids) is visible


@pytest.fixture
def attachments(people, media):
    ticket = TicketFactory(customer=people["customer"])
    public = CommentFactory(ticket=ticket, author=people["customer"])
    internal = CommentFactory(ticket=ticket, author=people["agent"], is_internal=True)
    deleted_ticket = TicketFactory(customer=people["customer"])
    created = {
        "ticket": AttachmentFactory(ticket=ticket, uploaded_by=people["customer"]),
        "public": AttachmentFactory(
            on_comment=True, comment=public, uploaded_by=people["customer"]
        ),
        "internal": AttachmentFactory(
            on_comment=True, comment=internal, uploaded_by=people["agent"]
        ),
        "deleted": AttachmentFactory(ticket=deleted_ticket, uploaded_by=people["customer"]),
    }
    deleted_ticket.delete()
    return created


ATTACHMENT_STATUSES = {
    "ticket": (401, 200, 404, 200, 200),
    "public": (401, 200, 404, 200, 200),
    "internal": (401, 404, 404, 200, 200),
    "deleted": (401, 404, 404, 404, 404),
}


@pytest.mark.parametrize("kind,role,expected", _cases(ATTACHMENT_STATUSES, ROLES))
def test_attachment_download(kind, role, expected, people, attachments):
    client = _client_for_role(role, people)
    response = client.get(f"/api/attachments/{attachments[kind].id}/download/")
    assert response.status_code == expected
    if expected == 200:
        assert set(response.data) == {"url", "expires_in"}


AVATAR_STATUSES = {
    "customer": (401, 200, 404, 200, 200),
    "agent": (401, 200, 200, 200, 200),
}


@pytest.mark.parametrize("owner,role,expected", _cases(AVATAR_STATUSES, ROLES))
def test_avatar_download(owner, role, expected, people, media):
    target = people[owner]
    target.avatar.save("avatar.png", ContentFile(b"avatar-bytes"), save=True)
    client = _client_for_role(role, people)
    response = client.get(f"/api/avatars/{target.id}/download/")
    assert response.status_code == expected


@pytest.mark.parametrize("role", ROLES)
def test_signed_links_work_for_everyone_who_holds_them(role, people, media):
    name = default_storage.save("downloads/matrix.txt", ContentFile(b"hello"))
    token = signing.dumps({"name": name, "content_type": "text/plain"}, salt=DOWNLOAD_SALT)
    client = _client_for_role(role, people)
    response = client.get(f"/api/downloads/{token}/")
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"hello"


@pytest.mark.parametrize("role", ROLES)
def test_forged_signed_links_are_refused_for_everyone(role, people, media):
    client = _client_for_role(role, people)
    assert client.get("/api/downloads/not-a-token/").status_code == 403
    forged = signing.dumps({"name": "x", "content_type": "text/plain"}, salt="another-salt")
    assert client.get(f"/api/downloads/{forged}/").status_code == 403


@pytest.fixture
def widget(db, media):
    site = SiteFactory(allowed_origins=[ORIGIN])
    visitor = VisitorFactory(site=site)
    other = VisitorFactory(site=site)
    ticket = TicketFactory(from_visitor=True, visitor=visitor)
    agent = AgentFactory()
    public = CommentFactory(ticket=ticket, author=None, visitor=visitor)
    internal = CommentFactory(ticket=ticket, author=agent, is_internal=True)
    return SimpleNamespace(
        site=site,
        visitor=visitor,
        other=other,
        ticket=ticket,
        public_attachment=AttachmentFactory(on_comment=True, comment=public, uploaded_by=None),
        internal_attachment=AttachmentFactory(on_comment=True, comment=internal, uploaded_by=agent),
    )


def _visitor_client(state, widget):
    tokens = {
        "owner": issue_visitor_token(widget.visitor),
        "bad_origin": issue_visitor_token(widget.visitor),
        "no_origin": issue_visitor_token(widget.visitor),
        "other_visitor": issue_visitor_token(widget.other),
        "invalid_token": "garbage",
    }
    headers = {}
    token = tokens.get(state)
    if token:
        headers["HTTP_X_VISITOR_TOKEN"] = token
    if state == "bad_origin":
        headers["HTTP_ORIGIN"] = EVIL_ORIGIN
    elif state != "no_origin":
        headers["HTTP_ORIGIN"] = ORIGIN
    client = APIClient()
    client.credentials(**headers)
    return client


def _text_upload():
    return SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")


WIDGET_CALLS = {
    "messages_get": lambda c, w: c.get(f"/api/widget/conversations/{w.ticket.id}/messages/"),
    "messages_post": lambda c, w: c.post(
        f"/api/widget/conversations/{w.ticket.id}/messages/", {"body": "hello"}, format="json"
    ),
    "read": lambda c, w: c.post(
        f"/api/widget/conversations/{w.ticket.id}/read/", {}, format="json"
    ),
    "upload": lambda c, w: c.post(
        f"/api/widget/conversations/{w.ticket.id}/attachments/", {"file": _text_upload()}
    ),
    "download_public": lambda c, w: c.get(
        f"/api/widget/attachments/{w.public_attachment.id}/download/"
    ),
    "download_internal": lambda c, w: c.get(
        f"/api/widget/attachments/{w.internal_attachment.id}/download/"
    ),
    "ws_ticket": lambda c, w: c.post("/api/widget/ws/ticket/"),
    "conversation_start": lambda c, w: c.post(
        "/api/widget/conversations/",
        {"body": "hello", "site_key": w.site.key},
        format="json",
    ),
    "rating_get": lambda c, w: c.get(f"/api/widget/conversations/{w.ticket.id}/rating/"),
    "rating_post": lambda c, w: c.post(
        f"/api/widget/conversations/{w.ticket.id}/rating/", {"score": 5}, format="json"
    ),
}
WIDGET_STATUSES = {
    "messages_get": (200, 404, 403, 403, 401, 401),
    "messages_post": (201, 404, 403, 403, 401, 401),
    "read": (200, 404, 403, 403, 401, 401),
    "upload": (201, 404, 403, 403, 401, 401),
    "download_public": (200, 404, 403, 403, 401, 401),
    "download_internal": (404, 404, 403, 403, 401, 401),
    "ws_ticket": (200, 200, 403, 403, 401, 401),
    "conversation_start": (200, 201, 403, 403, 201, 401),
    # The fixture ticket is open, so the owner reaches the view and gets the
    # "not resolved" conflict, while everyone else is stopped before it.
    "rating_get": (404, 404, 403, 403, 401, 401),
    "rating_post": (409, 404, 403, 403, 401, 401),
}


@pytest.mark.parametrize("route,state,expected", _cases(WIDGET_STATUSES, STATES))
def test_widget_routes(route, state, expected, widget):
    client = _visitor_client(state, widget)
    response = WIDGET_CALLS[route](client, widget)
    assert response.status_code == expected


@pytest.mark.parametrize(
    "origin,key,expected",
    [
        (ORIGIN, "valid", 200),
        (EVIL_ORIGIN, "valid", 403),
        (None, "valid", 403),
        (ORIGIN, "unknown", 404),
        (ORIGIN, None, 400),
    ],
)
def test_widget_config(origin, key, expected, db):
    site = SiteFactory(allowed_origins=[ORIGIN])
    params = {}
    if key == "valid":
        params["key"] = site.key
    elif key == "unknown":
        params["key"] = "does-not-exist"
    headers = {"HTTP_ORIGIN": origin} if origin else {}
    response = APIClient().get("/api/widget/config/", params, **headers)
    assert response.status_code == expected


def test_widget_config_of_a_deactivated_site_is_not_found(db):
    site = SiteFactory(allowed_origins=[ORIGIN])
    Site.objects.filter(pk=site.pk).update(is_active=False)
    response = APIClient().get("/api/widget/config/", {"key": site.key}, HTTP_ORIGIN=ORIGIN)
    assert response.status_code == 404


def test_a_deactivated_site_stops_its_visitors(widget):
    Site.objects.filter(pk=widget.site.pk).update(is_active=False)
    client = _visitor_client("owner", widget)
    response = WIDGET_CALLS["messages_get"](client, widget)
    assert response.status_code == 401
