from django.test import override_settings

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator

from config.asgi import application
from core.tests.factories import SiteFactory, UserFactory, VisitorFactory
from core.tickets import issue_ticket
from tickets.participants import Participant

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


def _expired_ticket(user):
    with override_settings(WS_TICKET_TTL_SECONDS=0):
        return issue_ticket(Participant(user=user))["ticket"]


async def test_connect_with_valid_user_ticket():
    user = await sync_to_async(UserFactory)()
    ticket = (await sync_to_async(issue_ticket)(Participant(user=user)))["ticket"]
    communicator = WebsocketCommunicator(application, f"/ws/?ticket={ticket}")
    connected, _ = await communicator.connect()
    assert connected
    await communicator.disconnect()


async def test_connect_with_valid_visitor_ticket():
    site = await sync_to_async(SiteFactory)(allowed_origins=["http://testserver"])
    visitor = await sync_to_async(VisitorFactory)(site=site)
    ticket = (await sync_to_async(issue_ticket)(Participant(visitor=visitor)))["ticket"]
    communicator = WebsocketCommunicator(
        application, f"/ws/?ticket={ticket}", headers=[(b"origin", b"http://testserver")]
    )
    connected, _ = await communicator.connect()
    assert connected
    await communicator.disconnect()


async def test_connect_visitor_with_bad_origin():
    site = await sync_to_async(SiteFactory)(allowed_origins=["http://allowed.com"])
    visitor = await sync_to_async(VisitorFactory)(site=site)
    ticket = (await sync_to_async(issue_ticket)(Participant(visitor=visitor)))["ticket"]
    communicator = WebsocketCommunicator(
        application, f"/ws/?ticket={ticket}", headers=[(b"origin", b"http://evil.com")]
    )
    connected, code = await communicator.connect()
    assert not connected
    assert code == 4401


async def test_connect_without_ticket():
    communicator = WebsocketCommunicator(application, "/ws/")
    connected, code = await communicator.connect()
    assert not connected
    assert code == 4401


async def test_connect_with_invalid_ticket():
    communicator = WebsocketCommunicator(application, "/ws/?ticket=invalid")
    connected, code = await communicator.connect()
    assert not connected
    assert code == 4401


async def test_disconnect_after_rejected_missing_ticket_does_not_raise():
    communicator = WebsocketCommunicator(application, "/ws/")
    connected, code = await communicator.connect()
    assert not connected
    assert code == 4401
    await communicator.disconnect()


async def test_disconnect_after_rejected_reused_ticket_does_not_raise():
    user = await sync_to_async(UserFactory)()
    ticket = (await sync_to_async(issue_ticket)(Participant(user=user)))["ticket"]

    first = WebsocketCommunicator(application, f"/ws/?ticket={ticket}")
    connected, _ = await first.connect()
    assert connected
    await first.disconnect()

    second = WebsocketCommunicator(application, f"/ws/?ticket={ticket}")
    connected, code = await second.connect()
    assert not connected
    assert code == 4401
    await second.disconnect()


async def test_disconnect_after_rejected_expired_ticket_does_not_raise():
    user = await sync_to_async(UserFactory)()
    ticket = await sync_to_async(_expired_ticket)(user)

    communicator = WebsocketCommunicator(application, f"/ws/?ticket={ticket}")
    connected, code = await communicator.connect()
    assert not connected
    assert code == 4401
    await communicator.disconnect()
