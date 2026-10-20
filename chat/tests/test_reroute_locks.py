import threading

from django.core.cache import cache
from django.db import connection, transaction

import pytest

from accounts.models import User
from chat import presence
from chat.assignment import route_queued_chats
from core.tests.factories import AgentFactory, TicketFactory
from tickets.assignment import release_tickets
from tickets.models import Ticket

pytestmark = pytest.mark.django_db(transaction=True)

JOIN_TIMEOUT = 5


def _hold_agent_lock(agent_pk, locked, release):
    try:
        with transaction.atomic():
            User.objects.select_for_update().get(pk=agent_pk)
            locked.set()
            release.wait(JOIN_TIMEOUT)
    finally:
        connection.close()


def _release(user, errors):
    try:
        release_tickets(user)
    except Exception as exc:
        errors.append(exc)
    finally:
        connection.close()


@pytest.fixture
def released_chat():
    cache.clear()
    released = AgentFactory()
    ticket = TicketFactory(from_visitor=True, assignee=released, status=Ticket.Status.OPEN)
    yield released, ticket
    cache.clear()


def _run_reroute_while_locked(released, locked_agent):
    locked, release = threading.Event(), threading.Event()
    holder = threading.Thread(target=_hold_agent_lock, args=(locked_agent.pk, locked, release))
    holder.start()
    errors = []
    try:
        assert locked.wait(JOIN_TIMEOUT)
        worker = threading.Thread(target=_release, args=(released, errors))
        worker.start()
        worker.join(JOIN_TIMEOUT)
        assert not worker.is_alive(), "the reroute waited on a locked agent row"
    finally:
        release.set()
        holder.join(JOIN_TIMEOUT)
    assert errors == []


def test_a_reroute_skips_a_locked_agent_and_assigns_a_free_one(released_chat):
    released, ticket = released_chat
    locked_agent = AgentFactory()
    free_agent = AgentFactory()
    presence.set_status(locked_agent.pk, presence.STATUS_AVAILABLE)
    presence.set_status(free_agent.pk, presence.STATUS_AVAILABLE)

    _run_reroute_while_locked(released, locked_agent)

    ticket.refresh_from_db()
    assert ticket.assignee == free_agent


def test_a_reroute_leaves_the_chat_queued_when_every_agent_is_locked(released_chat):
    released, ticket = released_chat
    locked_agent = AgentFactory()
    presence.set_status(locked_agent.pk, presence.STATUS_AVAILABLE)

    _run_reroute_while_locked(released, locked_agent)

    ticket.refresh_from_db()
    assert ticket.assignee is None
    assert ticket.channel == Ticket.Channel.CHAT
    assert route_queued_chats() == 1
    ticket.refresh_from_db()
    assert ticket.assignee == locked_agent
