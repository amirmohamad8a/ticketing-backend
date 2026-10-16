from types import SimpleNamespace

from django.test import override_settings

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from chat.models import Site
from config.asgi import application
from core.tests.factories import (
    AgentFactory,
    SiteFactory,
    TicketFactory,
    UserFactory,
    VisitorFactory,
)
from realtime.tickets import issue_ticket

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]

ORIGIN = "http://testserver"
OTHER_ORIGIN = "http://other.example"
CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_RATE_LIMITED = 4429
CLOSE_MESSAGE_TOO_BIG = 1009
CLOSE_UNSUPPORTED_DATA = 1003


def _build_world():
    site = SiteFactory(allowed_origins=[ORIGIN])
    other_site = SiteFactory(allowed_origins=[OTHER_ORIGIN])
    visitor_a = VisitorFactory(site=site)
    visitor_b = VisitorFactory(site=site)
    customer = UserFactory()
    return SimpleNamespace(
        site=site,
        other_site=other_site,
        visitor_a=visitor_a,
        visitor_b=visitor_b,
        customer=customer,
        other_customer=UserFactory(),
        agent=AgentFactory(),
        visitor_ticket_a=TicketFactory(from_visitor=True, visitor=visitor_a),
        visitor_ticket_b=TicketFactory(from_visitor=True, visitor=visitor_b),
        portal_ticket=TicketFactory(customer=customer),
    )


def _post_comment(user, ticket_id, body, internal):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client.post(
        f"/api/tickets/{ticket_id}/comments/",
        {"body": body, "is_internal": internal},
        format="json",
    )


async def _open(identity, origin=ORIGIN, path="/ws/"):
    token = (await sync_to_async(issue_ticket)(**identity))["ticket"]
    headers = [(b"origin", origin.encode())] if origin else []
    communicator = WebsocketCommunicator(application, f"{path}?ticket={token}", headers=headers)
    connected, code = await communicator.connect()
    return communicator, connected, code


async def _join(communicator, ticket_id):
    await communicator.send_json_to({"type": "join", "ticket_id": ticket_id})
    return await communicator.receive_json_from()


async def test_a_visitor_cannot_join_foreign_conversations():
    world = await sync_to_async(_build_world)()
    communicator, connected, _code = await _open({"visitor": world.visitor_a})
    assert connected
    for ticket in (world.visitor_ticket_b, world.portal_ticket):
        reply = await _join(communicator, ticket.id)
        assert reply == {"type": "error", "code": "not_found", "ticket_id": ticket.id}
    own = await _join(communicator, world.visitor_ticket_a.id)
    assert own["type"] == "joined"
    await communicator.disconnect()


async def test_a_customer_cannot_join_foreign_or_visitor_tickets():
    world = await sync_to_async(_build_world)()
    other_ticket = await sync_to_async(TicketFactory)(customer=world.other_customer)
    communicator, connected, _code = await _open({"user": world.customer})
    assert connected
    for ticket in (other_ticket, world.visitor_ticket_a):
        reply = await _join(communicator, ticket.id)
        assert reply["code"] == "not_found"
    assert (await _join(communicator, world.portal_ticket.id))["type"] == "joined"
    await communicator.disconnect()


async def test_nobody_can_join_a_deleted_ticket():
    world = await sync_to_async(_build_world)()
    await sync_to_async(world.portal_ticket.delete)()
    for user in (world.customer, world.agent):
        communicator, connected, _code = await _open({"user": user})
        assert connected
        reply = await _join(communicator, world.portal_ticket.id)
        assert reply["code"] == "not_found"
        await communicator.disconnect()


async def test_the_presence_socket_is_for_staff_only():
    world = await sync_to_async(_build_world)()
    _comm, connected, code = await _open({"user": world.customer}, path="/ws/presence/")
    assert not connected
    assert code == CLOSE_FORBIDDEN
    _comm, connected, code = await _open({"visitor": world.visitor_a}, path="/ws/presence/")
    assert not connected
    assert code == CLOSE_UNAUTHENTICATED


async def test_a_socket_ticket_works_only_once():
    world = await sync_to_async(_build_world)()
    token = (await sync_to_async(issue_ticket)(user=world.customer))["ticket"]
    first = WebsocketCommunicator(application, f"/ws/?ticket={token}")
    second = WebsocketCommunicator(application, f"/ws/?ticket={token}")
    connected, _code = await first.connect()
    assert connected
    connected, code = await second.connect()
    assert not connected
    assert code == CLOSE_UNAUTHENTICATED
    await first.disconnect()


async def test_tampered_and_truncated_socket_tickets_are_refused():
    world = await sync_to_async(_build_world)()
    token = (await sync_to_async(issue_ticket)(user=world.customer))["ticket"]
    swapped = token[:-1] + ("A" if token[-1] != "A" else "B")
    for candidate in (swapped, token[:10], token + token, "x" * 40):
        communicator = WebsocketCommunicator(application, f"/ws/?ticket={candidate}")
        connected, code = await communicator.connect()
        assert not connected
        assert code == CLOSE_UNAUTHENTICATED


async def test_an_expired_socket_ticket_is_refused():
    world = await sync_to_async(_build_world)()
    with override_settings(WS_TICKET_TTL_SECONDS=-1):
        token = (await sync_to_async(issue_ticket)(user=world.customer))["ticket"]
    communicator = WebsocketCommunicator(application, f"/ws/?ticket={token}")
    connected, code = await communicator.connect()
    assert not connected
    assert code == CLOSE_UNAUTHENTICATED


async def test_a_ticket_of_a_deactivated_user_is_refused():
    world = await sync_to_async(_build_world)()
    token = (await sync_to_async(issue_ticket)(user=world.customer))["ticket"]
    await sync_to_async(User.objects.filter(pk=world.customer.pk).update)(is_active=False)
    communicator = WebsocketCommunicator(application, f"/ws/?ticket={token}")
    connected, code = await communicator.connect()
    assert not connected
    assert code == CLOSE_UNAUTHENTICATED


async def test_a_ticket_of_a_visitor_of_a_deactivated_site_is_refused():
    world = await sync_to_async(_build_world)()
    token = (await sync_to_async(issue_ticket)(visitor=world.visitor_a))["ticket"]
    await sync_to_async(Site.objects.filter(pk=world.site.pk).update)(is_active=False)
    headers = [(b"origin", ORIGIN.encode())]
    communicator = WebsocketCommunicator(application, f"/ws/?ticket={token}", headers=headers)
    connected, code = await communicator.connect()
    assert not connected
    assert code == CLOSE_UNAUTHENTICATED


async def test_a_visitor_socket_needs_an_origin_of_its_own_site():
    world = await sync_to_async(_build_world)()
    for origin in (None, "http://evil.example", OTHER_ORIGIN, "null", ORIGIN + ".evil.example"):
        _comm, connected, code = await _open({"visitor": world.visitor_a}, origin=origin)
        assert not connected, origin
        assert code == CLOSE_UNAUTHENTICATED


async def test_an_oversized_frame_closes_the_connection():
    world = await sync_to_async(_build_world)()
    communicator, connected, _code = await _open({"user": world.customer})
    assert connected
    await communicator.send_to(text_data="x" * 5000)
    output = await communicator.receive_output(timeout=1)
    assert output["type"] == "websocket.close"
    assert output["code"] == CLOSE_MESSAGE_TOO_BIG
    await communicator.disconnect()


async def test_a_binary_frame_closes_the_connection():
    world = await sync_to_async(_build_world)()
    communicator, connected, _code = await _open({"user": world.customer})
    assert connected
    await communicator.send_to(bytes_data=b"\x00\x01")
    output = await communicator.receive_output(timeout=1)
    assert output["type"] == "websocket.close"
    assert output["code"] == CLOSE_UNSUPPORTED_DATA
    await communicator.disconnect()


async def test_a_message_flood_closes_the_connection():
    world = await sync_to_async(_build_world)()
    with override_settings(WS_RATE_LIMIT_MESSAGES=3, WS_RATE_LIMIT_WINDOW_SECONDS=60):
        communicator, connected, _code = await _open({"user": world.customer})
        assert connected
        for _round in range(3):
            await communicator.send_json_to({"type": "ping"})
            assert await communicator.receive_json_from() == {"type": "pong"}
        await communicator.send_json_to({"type": "ping"})
        output = await communicator.receive_output(timeout=1)
    assert output["type"] == "websocket.close"
    assert output["code"] == CLOSE_RATE_LIMITED
    await communicator.disconnect()


async def test_malformed_messages_are_answered_with_errors_and_never_crash_the_socket():
    world = await sync_to_async(_build_world)()
    communicator, connected, _code = await _open({"user": world.customer})
    assert connected
    await communicator.send_to(text_data="[" * 4000)
    assert (await communicator.receive_json_from())["code"] == "invalid_json"
    await communicator.send_json_to([1, 2])
    assert (await communicator.receive_json_from())["code"] == "invalid_message"
    await communicator.send_json_to({"type": "nope"})
    assert (await communicator.receive_json_from())["code"] == "unknown_type"
    for bad in (0, -1, True, "1", 2**63, 1.5, None):
        reply = await _join(communicator, bad)
        assert reply["code"] == "invalid_ticket_id", bad
    await communicator.send_json_to({"type": "typing", "ticket_id": world.portal_ticket.id})
    assert (await communicator.receive_json_from())["code"] == "invalid_message"
    await communicator.send_json_to(
        {"type": "typing", "ticket_id": world.portal_ticket.id, "is_typing": True}
    )
    assert (await communicator.receive_json_from())["code"] == "not_joined"
    await communicator.disconnect()


async def test_internal_notes_never_reach_the_customer_socket():
    world = await sync_to_async(_build_world)()
    communicator, connected, _code = await _open({"user": world.customer})
    assert connected
    assert (await _join(communicator, world.portal_ticket.id))["type"] == "joined"
    await sync_to_async(_post_comment)(world.agent, world.portal_ticket.id, "secret", True)
    assert await communicator.receive_nothing(timeout=0.5) is True
    await sync_to_async(_post_comment)(world.agent, world.portal_ticket.id, "hello", False)
    event = await communicator.receive_json_from()
    assert event["type"] == "message.created"
    assert event["data"]["is_internal"] is False
    await communicator.disconnect()
