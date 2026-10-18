from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.utils import translation
from django.utils.functional import Promise

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import TicketFactory, UserFactory
from tickets.permissions import AdminOnlyDeleteAndRestore


class LocaleSettingsTests(TestCase):
    def test_language_and_time_zone_settings(self):
        self.assertEqual(settings.LANGUAGE_CODE, "fa")
        self.assertEqual(settings.TIME_ZONE, "Asia/Tehran")
        self.assertTrue(settings.USE_TZ)
        self.assertTrue(settings.USE_I18N)

    def test_persian_is_the_active_language(self):
        self.assertEqual(translation.get_language(), "fa")

    def test_framework_validation_messages_are_translated(self):
        response = APIClient().post("/api/auth/register/", {}, format="json")
        message = response.data["error"]["details"]["username"][0]
        self.assertNotEqual(message, "This field is required.")

    def test_class_level_messages_are_lazy(self):
        self.assertIsInstance(AdminOnlyDeleteAndRestore.message, Promise)


class TimeZoneBehaviourTests(TestCase):
    def test_api_returns_timestamps_in_tehran_time(self):
        customer = UserFactory()
        client = APIClient()
        refresh = RefreshToken.for_user(customer)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        response = client.post("/api/tickets/", {"title": "t", "description": "d"})
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["created_at"].endswith("+03:30"))
        self.assertTrue(response.data["updated_at"].endswith("+03:30"))

    def test_database_values_stay_in_utc(self):
        ticket = TicketFactory()
        ticket.refresh_from_db()
        self.assertEqual(ticket.created_at.utcoffset(), timedelta(0))
