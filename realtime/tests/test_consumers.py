import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator

from config.asgi import application
from core.tests.factories import AgentFactory, TicketFactory, UserFactory
from core.tickets import issue_ticket

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


async def test_join_and_leave_ticket():
    user = await sync_to_async(UserFactory)()
    ticket = await sync_to_async(TicketFactory)(customer=user)
    ws_ticket = (await sync_to_async(issue_ticket)(user=user))["ticket"]

    communicator = WebsocketCommunicator(application, f"/ws/?ticket={ws_ticket}")
    connected, _ = await communicator.connect()
    assert connected

    await communicator.send_json_to({"type": "join", "ticket_id": ticket.id})
    response = await communicator.receive_json_from()
    assert response == {"type": "joined", "ticket_id": ticket.id}

    await communicator.send_json_to({"type": "leave", "ticket_id": ticket.id})
    response = await communicator.receive_json_from()
    assert response == {"type": "left", "ticket_id": ticket.id}

    await communicator.disconnect()


async def test_join_ticket_not_found():
    user = await sync_to_async(UserFactory)()
    ws_ticket = (await sync_to_async(issue_ticket)(user=user))["ticket"]

    communicator = WebsocketCommunicator(application, f"/ws/?ticket={ws_ticket}")
    await communicator.connect()

    await communicator.send_json_to({"type": "join", "ticket_id": 99999})
    response = await communicator.receive_json_from()
    assert response["type"] == "error"
    assert response["code"] == "not_found"

    await communicator.disconnect()


async def test_customer_cannot_join_other_ticket():
    customer1 = await sync_to_async(UserFactory)()
    customer2 = await sync_to_async(UserFactory)()
    ticket2 = await sync_to_async(TicketFactory)(customer=customer2)

    ws_ticket = (await sync_to_async(issue_ticket)(user=customer1))["ticket"]
    communicator = WebsocketCommunicator(application, f"/ws/?ticket={ws_ticket}")
    await communicator.connect()

    await communicator.send_json_to({"type": "join", "ticket_id": ticket2.id})
    response = await communicator.receive_json_from()
    assert response["type"] == "error"
    assert response["code"] == "not_found"

    await communicator.disconnect()


async def test_typing_fanout():
    user1 = await sync_to_async(UserFactory)()
    user2 = await sync_to_async(AgentFactory)()
    ticket = await sync_to_async(TicketFactory)(customer=user1, assignee=user2)

    ws_ticket1 = (await sync_to_async(issue_ticket)(user=user1))["ticket"]
    ws_ticket2 = (await sync_to_async(issue_ticket)(user=user2))["ticket"]

    comm1 = WebsocketCommunicator(application, f"/ws/?ticket={ws_ticket1}")
    comm2 = WebsocketCommunicator(application, f"/ws/?ticket={ws_ticket2}")

    await comm1.connect()
    await comm2.connect()

    await comm1.send_json_to({"type": "join", "ticket_id": ticket.id})
    await comm1.receive_json_from()

    await comm2.send_json_to({"type": "join", "ticket_id": ticket.id})
    await comm2.receive_json_from()

    await comm1.send_json_to({"type": "typing", "ticket_id": ticket.id, "is_typing": True})

    response = await comm2.receive_json_from()
    assert response["type"] == "typing"
    assert response["ticket_id"] == ticket.id
    assert response["is_typing"] is True

    await comm1.disconnect()
    await comm2.disconnect()
