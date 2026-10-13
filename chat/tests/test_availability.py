from django.test import TestCase

from chat.availability import agents_available
from core.tests.factories import AdminFactory, AgentFactory, SiteFactory


class AvailabilityTests(TestCase):
    def setUp(self):
        self.site = SiteFactory()

    def test_no_agents(self):
        self.assertFalse(agents_available(self.site))

    def test_active_agent(self):
        AgentFactory()
        self.assertTrue(agents_available(self.site))

    def test_inactive_agent(self):
        AgentFactory(is_active=False)
        self.assertFalse(agents_available(self.site))

    def test_active_admin(self):
        AdminFactory()
        self.assertTrue(agents_available(self.site))
