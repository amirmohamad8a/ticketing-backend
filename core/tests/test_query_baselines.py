from unittest.mock import patch

from django.core.cache import cache

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from chat import presence
from chat.conversations import start_conversation
from chat.tokens import issue_visitor_token
from core.tests import read_streaming_body
from core.tests.factories import (
    AdminFactory,
    AgentFactory,
    CommentFactory,
    SiteFactory,
    TagFactory,
    TicketEventFactory,
    TicketFactory,
    UserFactory,
)
from tickets import export

pytestmark = pytest.mark.django_db


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _widget_client(visitor):
    client = APIClient()
    client.credentials(
        HTTP_X_VISITOR_TOKEN=issue_visitor_token(visitor),
        HTTP_ORIGIN="https://example.com",
    )
    return client


def _ticket_list_world():
    agent = AgentFactory()
    customer = UserFactory()
    tags = [TagFactory(name=f"baseline-{index}") for index in range(2)]
    for _ in range(3):
        TicketFactory(customer=customer, assignee=agent, tags=tags, status="open")
        TicketFactory(from_visitor=True, assignee=agent, tags=tags[:1], status="in_progress")
    return agent, customer


def test_ticket_list_as_agent(django_assert_max_num_queries):
    agent, _customer = _ticket_list_world()
    client = _client_for(agent)

    with django_assert_max_num_queries(4):
        response = client.get("/api/tickets/")

    assert response.status_code == 200


def test_ticket_list_as_customer(django_assert_max_num_queries):
    _agent, customer = _ticket_list_world()
    client = _client_for(customer)

    with django_assert_max_num_queries(3):
        response = client.get("/api/tickets/")

    assert response.status_code == 200


def test_ticket_messages(django_assert_max_num_queries):
    agent = AgentFactory()
    customer = UserFactory()
    ticket = TicketFactory(customer=customer, assignee=agent)
    for index in range(3):
        CommentFactory(ticket=ticket, author=agent, body=f"agent {index}")
        CommentFactory(ticket=ticket, author=customer, body=f"customer {index}")
    client = _client_for(agent)

    with django_assert_max_num_queries(5):
        response = client.get(f"/api/tickets/{ticket.id}/messages/")

    assert response.status_code == 200


def test_widget_messages(django_assert_max_num_queries):
    agent = AgentFactory()
    site = SiteFactory(allowed_origins=["https://example.com"])
    _session, ticket, _comment = start_conversation(site, "Hello")
    for index in range(3):
        CommentFactory(ticket=ticket, author=agent, body=f"reply {index}")
    client = _widget_client(ticket.visitor)

    with django_assert_max_num_queries(8):
        response = client.get(f"/api/widget/conversations/{ticket.id}/messages/")

    assert response.status_code == 200


def test_stats(django_assert_max_num_queries):
    agent = AgentFactory()
    customer = UserFactory()
    for _ in range(3):
        TicketFactory(customer=customer, assignee=agent)
    client = _client_for(agent)

    with django_assert_max_num_queries(8):
        response = client.get("/api/stats/")

    assert response.status_code == 200


def test_audit(django_assert_max_num_queries):
    admin = AdminFactory()
    ticket = TicketFactory()
    for _ in range(5):
        TicketEventFactory(ticket=ticket)
    client = _client_for(admin)

    with django_assert_max_num_queries(4):
        response = client.get("/api/audit/")

    assert response.status_code == 200


def test_online_agents(django_assert_max_num_queries):
    cache.clear()
    requester = AgentFactory()
    for _ in range(3):
        presence.heartbeat(AgentFactory().pk)
    client = _client_for(requester)

    with django_assert_max_num_queries(3):
        response = client.get("/api/agents/online/")

    assert response.status_code == 200
    cache.clear()


def test_export_per_batch(django_assert_max_num_queries):
    agent = AgentFactory()
    for _ in range(5):
        TicketFactory(assignee=agent)
    client = _client_for(agent)

    with patch.object(export, "EXPORT_BATCH_SIZE", 2):
        with django_assert_max_num_queries(11):
            response = client.get("/api/tickets/export/")
            body = read_streaming_body(response)

    assert response.status_code == 200
    assert len(body) > 0
