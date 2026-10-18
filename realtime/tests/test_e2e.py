import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from chat.conversations import start_conversation
from config.asgi import application
from core.tests.factories import AgentFactory, SiteFactory
from core.tickets import issue_ticket

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


async def test_visitor_message_to_agent_reply_e2e():
    site = await sync_to_async(SiteFactory)(allowed_origins=["http://testserver"])
    agent = await sync_to_async(AgentFactory)()

    session, ticket, comment = await sync_to_async(start_conversation)(site, "Hello", name="Test")
    visitor = session.visitor

    @sync_to_async
    def assign_ticket():
        ticket.assignee = agent
        ticket.save()

    await assign_ticket()

    visitor_ws_ticket = (await sync_to_async(issue_ticket)(visitor=visitor))["ticket"]
    agent_ws_ticket = (await sync_to_async(issue_ticket)(user=agent))["ticket"]

    visitor_comm = WebsocketCommunicator(
        application, f"/ws/?ticket={visitor_ws_ticket}", headers=[(b"origin", b"http://testserver")]
    )
    agent_comm = WebsocketCommunicator(application, f"/ws/?ticket={agent_ws_ticket}")

    await visitor_comm.connect()
    await agent_comm.connect()

    await visitor_comm.send_json_to({"type": "join", "ticket_id": ticket.id})
    join_response = await visitor_comm.receive_json_from()
    assert join_response["type"] == "joined", f"Visitor failed to join: {join_response}"

    await agent_comm.send_json_to({"type": "join", "ticket_id": ticket.id})
    agent_join_response = await agent_comm.receive_json_from()
    assert agent_join_response["type"] == "joined", f"Agent failed to join: {agent_join_response}"

    @sync_to_async
    def visitor_post():
        client = APIClient()
        return client.post(
            f"/api/widget/conversations/{ticket.id}/messages/",
            {"body": "Second message"},
            HTTP_X_VISITOR_TOKEN=session.token,
            HTTP_ORIGIN="http://testserver",
        )

    await visitor_post()

    agent_event = await agent_comm.receive_json_from()
    assert agent_event["type"] == "message.created"
    assert agent_event["ticket_id"] == ticket.id

    @sync_to_async
    def agent_post():
        client = APIClient()
        refresh = RefreshToken.for_user(agent)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        return client.post(
            f"/api/tickets/{ticket.id}/comments/",
            {"body": "Agent reply"},
            format="json",
        )

    await agent_post()

    visitor_event = await visitor_comm.receive_json_from()
    assert visitor_event["type"] == "message.created"
    assert visitor_event["ticket_id"] == ticket.id

    await visitor_comm.disconnect()
    await agent_comm.disconnect()
