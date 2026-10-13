from django.core.cache import cache
from django.test import TestCase

from chat.availability import agents_available
from core.tests.factories import AdminFactory, AgentFactory, SiteFactory, UserFactory
from realtime import presence


class AvailabilityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.site = SiteFactory()

    def test_no_agents(self):
        self.assertFalse(agents_available(self.site))

    def test_agent_without_a_presence_entry_is_not_available(self):
        AgentFactory()
        self.assertFalse(agents_available(self.site))

    def test_available_agent(self):
        agent = AgentFactory()
        presence.heartbeat(agent.pk)
        self.assertTrue(agents_available(self.site))

    def test_available_admin(self):
        admin = AdminFactory()
        presence.heartbeat(admin.pk)
        self.assertTrue(agents_available(self.site))

    def test_away_agent_is_not_available(self):
        agent = AgentFactory()
        presence.set_status(agent.pk, presence.STATUS_AWAY)
        self.assertFalse(agents_available(self.site))

    def test_inactive_agent_is_not_available_even_with_presence(self):
        agent = AgentFactory(is_active=False)
        presence.heartbeat(agent.pk)
        self.assertFalse(agents_available(self.site))

    def test_customer_is_never_available(self):
        customer = UserFactory()
        presence.heartbeat(customer.pk)
        self.assertFalse(agents_available(self.site))

    def test_one_available_agent_is_enough(self):
        away = AgentFactory()
        available = AgentFactory()
        presence.set_status(away.pk, presence.STATUS_AWAY)
        presence.heartbeat(available.pk)
        self.assertTrue(agents_available(self.site))
