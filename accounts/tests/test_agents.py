from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from core.tests.factories import AdminFactory, AgentFactory, TicketFactory, UserFactory

URL = "/api/agents/"


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class AgentListPermissionTests(TestCase):
    def test_unauthenticated_request_is_rejected(self):
        response = APIClient().get(URL)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["error"]["code"], "not_authenticated")

    def test_customer_is_forbidden(self):
        response = _client_for(UserFactory()).get(URL)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error"]["code"], "permission_denied")

    def test_agent_and_admin_can_read_the_list(self):
        for user in (AgentFactory(), AdminFactory()):
            with self.subTest(role=user.role):
                response = _client_for(user).get(URL)
                self.assertEqual(response.status_code, 200)

    def test_the_list_is_read_only(self):
        client = _client_for(AgentFactory())
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(client, method)(URL)
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response.data["error"]["code"], "method_not_allowed")

    def test_customer_cannot_write_either(self):
        response = _client_for(UserFactory()).post(URL, {}, format="json")
        self.assertEqual(response.status_code, 403)


class AgentListContentTests(TestCase):
    def setUp(self):
        self.requester = AdminFactory(first_name="Dara", last_name="Mohammadi")
        self.client = _client_for(self.requester)

    def _ids(self, response=None):
        response = response or self.client.get(URL)
        return [item["id"] for item in response.data]

    def test_only_active_agents_and_admins_are_listed(self):
        agent = AgentFactory()
        admin = AdminFactory()
        UserFactory()
        AgentFactory(is_active=False)
        AdminFactory(is_active=False)
        UserFactory(is_active=False)
        self.assertEqual(set(self._ids()), {self.requester.id, agent.id, admin.id})

    def test_the_requester_is_included(self):
        self.assertIn(self.requester.id, self._ids())

    def test_an_agent_sees_the_same_list_as_an_admin(self):
        agent = AgentFactory()
        as_agent = self._ids(_client_for(agent).get(URL))
        as_admin = self._ids()
        self.assertEqual(as_agent, as_admin)
        self.assertIn(agent.id, as_agent)

    def test_rows_expose_only_id_name_and_role(self):
        agent = AgentFactory(
            first_name="Sara",
            last_name="Ahmadi",
            phone="09123456789",
            email="sara@example.com",
        )
        response = self.client.get(URL)
        row = next(item for item in response.data if item["id"] == agent.id)
        self.assertEqual(row, {"id": agent.id, "name": "Sara Ahmadi", "role": User.Role.AGENT})
        for item in response.data:
            self.assertEqual(set(item), {"id", "name", "role"})

    def test_roles_are_reported_as_stored(self):
        agent = AgentFactory()
        roles = {item["id"]: item["role"] for item in self.client.get(URL).data}
        self.assertEqual(roles[agent.id], User.Role.AGENT)
        self.assertEqual(roles[self.requester.id], User.Role.ADMIN)

    def test_name_uses_the_full_name_when_there_is_one(self):
        both = AgentFactory(first_name="Sara", last_name="Ahmadi")
        first_only = AgentFactory(first_name="Mina", last_name="")
        last_only = AgentFactory(first_name="", last_name="Rezaei")
        persian = AgentFactory(first_name="علی", last_name="رضایی")
        names = {item["id"]: item["name"] for item in self.client.get(URL).data}
        self.assertEqual(names[both.id], "Sara Ahmadi")
        self.assertEqual(names[first_only.id], "Mina")
        self.assertEqual(names[last_only.id], "Rezaei")
        self.assertEqual(names[persian.id], "علی رضایی")

    def test_name_falls_back_to_the_username(self):
        agent = AgentFactory(username="support_bot", first_name="", last_name="")
        names = {item["id"]: item["name"] for item in self.client.get(URL).data}
        self.assertEqual(names[agent.id], "support_bot")

    def test_rows_are_sorted_by_name(self):
        AgentFactory(first_name="Bita", last_name="Karimi")
        AdminFactory(first_name="Cyrus", last_name="Naderi")
        AgentFactory(first_name="Ali", last_name="Zand")
        names = [item["name"] for item in self.client.get(URL).data]
        self.assertEqual(names, ["Ali Zand", "Bita Karimi", "Cyrus Naderi", "Dara Mohammadi"])

    def test_ties_are_broken_by_last_name_then_id(self):
        second = AgentFactory(first_name="Bita", last_name="Zand")
        first = AgentFactory(first_name="Bita", last_name="Amini")
        twin_a = AgentFactory(first_name="Bita", last_name="Zand")
        ids = self._ids()
        self.assertLess(ids.index(first.id), ids.index(second.id))
        self.assertLess(ids.index(second.id), ids.index(twin_a.id))

    def test_list_is_not_paginated(self):
        AgentFactory.create_batch(25)
        response = self.client.get(URL)
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 26)

    def test_deactivated_agents_disappear_and_reactivated_ones_return(self):
        agent = AgentFactory()
        self.assertIn(agent.id, self._ids())
        User.objects.filter(pk=agent.pk).update(is_active=False)
        self.assertNotIn(agent.id, self._ids())
        User.objects.filter(pk=agent.pk).update(is_active=True)
        self.assertIn(agent.id, self._ids())

    def test_demoted_agents_disappear(self):
        agent = AgentFactory()
        User.objects.filter(pk=agent.pk).update(role=User.Role.CUSTOMER)
        self.assertNotIn(agent.id, self._ids())

    def test_every_listed_user_is_a_valid_assignee(self):
        AgentFactory.create_batch(2)
        AdminFactory()
        UserFactory()
        AgentFactory(is_active=False)
        ticket = TicketFactory()
        listed = self.client.get(URL).data
        self.assertEqual(len(listed), 4)
        for item in listed:
            with self.subTest(user=item["id"]):
                response = self.client.patch(
                    f"/api/tickets/{ticket.id}/", {"assignee": item["id"]}, format="json"
                )
                self.assertEqual(response.status_code, 200)

    def _query_count(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        return len(queries)

    def test_query_count_does_not_grow_with_the_number_of_agents(self):
        AgentFactory.create_batch(2)
        few = self._query_count()
        AgentFactory.create_batch(10)
        self.assertEqual(self._query_count(), few)


class AgentSchemaTests(TestCase):
    def test_route_is_documented_under_the_agents_tag(self):
        response = APIClient().get("/api/schema/?format=json")
        self.assertEqual(response.status_code, 200)
        operation = response.json()["paths"]["/api/agents/"]["get"]
        self.assertEqual(operation["tags"], ["Agents"])
