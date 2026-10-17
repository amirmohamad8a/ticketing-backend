from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from accounts.permissions import IsAgentOrAdmin
from core.tests.factories import AdminFactory, AgentFactory, TicketFactory, UserFactory
from tickets.permissions import IsCustomerOwnerOrReadOwn


def _request(user):
    return SimpleNamespace(user=user)


class IsAgentOrAdminTests(TestCase):
    def setUp(self):
        self.permission = IsAgentOrAdmin()

    def _allowed(self, user):
        return self.permission.has_permission(_request(user), None)

    def test_agent_is_allowed(self):
        self.assertTrue(self._allowed(AgentFactory()))

    def test_admin_is_allowed(self):
        self.assertTrue(self._allowed(AdminFactory()))

    def test_customer_is_denied(self):
        self.assertFalse(self._allowed(UserFactory()))

    def test_anonymous_user_is_denied(self):
        self.assertFalse(self._allowed(AnonymousUser()))

    def test_missing_user_is_denied(self):
        self.assertFalse(self._allowed(None))


class IsCustomerOwnerOrReadOwnTests(TestCase):
    def setUp(self):
        self.permission = IsCustomerOwnerOrReadOwn()
        self.owner = UserFactory()
        self.ticket = TicketFactory(customer=self.owner)

    def _has_object(self, user):
        return self.permission.has_object_permission(_request(user), None, self.ticket)

    def test_authenticated_user_passes_view_level_check(self):
        self.assertTrue(self.permission.has_permission(_request(self.owner), None))

    def test_anonymous_user_fails_view_level_check(self):
        self.assertFalse(self.permission.has_permission(_request(AnonymousUser()), None))

    def test_missing_user_fails_view_level_check(self):
        self.assertFalse(self.permission.has_permission(_request(None), None))

    def test_owner_is_allowed_on_object(self):
        self.assertTrue(self._has_object(self.owner))

    def test_other_customer_is_denied_on_object(self):
        self.assertFalse(self._has_object(UserFactory()))

    def test_agent_is_allowed_on_any_object(self):
        self.assertTrue(self._has_object(AgentFactory()))

    def test_admin_is_allowed_on_any_object(self):
        self.assertTrue(self._has_object(AdminFactory()))
