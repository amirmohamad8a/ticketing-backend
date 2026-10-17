import asyncio

from django.test import override_settings

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator

from config.asgi import application
from core.tests.factories import AgentFactory, UserFactory
from realtime import presence
from realtime.tickets import issue_ticket

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


async def test_presence_connect_and_heartbeat():
    agent = await sync_to_async(AgentFactory)()
    ws_ticket = (await sync_to_async(issue_ticket)(user=agent))["ticket"]

    communicator = WebsocketCommunicator(application, f"/ws/presence/?ticket={ws_ticket}")
    connected, _ = await communicator.connect()
    assert connected

    response = await communicator.receive_json_from()
    assert response == {"type": "presence", "status": "available"}

    await communicator.send_json_to({"type": "ping"})
    response = await communicator.receive_json_from()
    assert response == {"type": "pong", "status": "available"}

    await communicator.disconnect()


async def test_presence_customer_rejected():
    customer = await sync_to_async(UserFactory)()
    ws_ticket = (await sync_to_async(issue_ticket)(user=customer))["ticket"]

    communicator = WebsocketCommunicator(application, f"/ws/presence/?ticket={ws_ticket}")
    connected, code = await communicator.connect()
    assert not connected
    assert code == 4403


async def test_presence_set_status():
    agent = await sync_to_async(AgentFactory)()
    ws_ticket = (await sync_to_async(issue_ticket)(user=agent))["ticket"]

    communicator = WebsocketCommunicator(application, f"/ws/presence/?ticket={ws_ticket}")
    await communicator.connect()
    await communicator.receive_json_from()

    await communicator.send_json_to({"type": "set_status", "status": "away"})
    response = await communicator.receive_json_from()
    assert response == {"type": "presence", "status": "away"}

    await communicator.disconnect()


@override_settings(PRESENCE_TTL_SECONDS=1)
async def test_presence_expiry():
    agent = await sync_to_async(AgentFactory)()
    await sync_to_async(presence.heartbeat)(agent.pk)
    statuses = await sync_to_async(presence.get_statuses)([agent.pk])
    assert statuses.get(agent.pk) == "available"
    await asyncio.sleep(1.1)
    statuses_after = await sync_to_async(presence.get_statuses)([agent.pk])
    assert statuses_after.get(agent.pk) is None


async def test_presence_rejects_bad_messages():
    agent = await sync_to_async(AgentFactory)()
    ws_ticket = (await sync_to_async(issue_ticket)(user=agent))["ticket"]
    communicator = WebsocketCommunicator(application, f"/ws/presence/?ticket={ws_ticket}")
    await communicator.connect()
    await communicator.receive_json_from()

    await communicator.send_to(text_data="[" * 4000)
    assert (await communicator.receive_json_from())["code"] == "invalid_json"
    await communicator.send_json_to([1, 2])
    assert (await communicator.receive_json_from())["code"] == "invalid_message"
    await communicator.send_json_to({"type": "nope"})
    assert (await communicator.receive_json_from())["code"] == "unknown_type"
    await communicator.send_json_to({"type": "set_status", "status": "bogus"})
    assert (await communicator.receive_json_from())["code"] == "invalid_status"

    await communicator.disconnect()


async def test_presence_closes_on_a_binary_frame():
    agent = await sync_to_async(AgentFactory)()
    ws_ticket = (await sync_to_async(issue_ticket)(user=agent))["ticket"]
    communicator = WebsocketCommunicator(application, f"/ws/presence/?ticket={ws_ticket}")
    await communicator.connect()
    await communicator.receive_json_from()
    await communicator.send_to(bytes_data=b"\x00\x01")
    output = await communicator.receive_output(timeout=1)
    assert output["type"] == "websocket.close"
    assert output["code"] == 1003
    await communicator.disconnect()


async def test_presence_closes_on_an_oversized_frame():
    agent = await sync_to_async(AgentFactory)()
    ws_ticket = (await sync_to_async(issue_ticket)(user=agent))["ticket"]
    communicator = WebsocketCommunicator(application, f"/ws/presence/?ticket={ws_ticket}")
    await communicator.connect()
    await communicator.receive_json_from()
    await communicator.send_to(text_data="x" * 5000)
    output = await communicator.receive_output(timeout=1)
    assert output["type"] == "websocket.close"
    assert output["code"] == 1009
    await communicator.disconnect()


@override_settings(WS_RATE_LIMIT_MESSAGES=1, WS_RATE_LIMIT_WINDOW_SECONDS=60)
async def test_presence_closes_on_a_message_flood():
    agent = await sync_to_async(AgentFactory)()
    ws_ticket = (await sync_to_async(issue_ticket)(user=agent))["ticket"]
    communicator = WebsocketCommunicator(application, f"/ws/presence/?ticket={ws_ticket}")
    await communicator.connect()
    await communicator.receive_json_from()

    await communicator.send_json_to({"type": "ping"})
    assert (await communicator.receive_json_from())["type"] == "pong"
    await communicator.send_json_to({"type": "ping"})
    output = await communicator.receive_output(timeout=1)
    assert output["type"] == "websocket.close"
    assert output["code"] == 4429
    await communicator.disconnect()
