from unittest.mock import patch

from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from chat.models import Site
from chat.tokens import issue_visitor_token
from core.tests.factories import (
    AdminFactory,
    AgentFactory,
    TicketFactory,
    TicketRatingFactory,
    UserFactory,
    VisitorFactory,
)
from tickets.models import Ticket, TicketRating
from tickets.ratings import TicketAlreadyRated, TicketNotResolved, rate_ticket

RATING_KEYS = {"score", "comment", "created_at"}
UNFINISHED = (
    Ticket.Status.OPEN,
    Ticket.Status.IN_PROGRESS,
    Ticket.Status.WAITING_ON_CUSTOMER,
)
FINISHED = (Ticket.Status.RESOLVED, Ticket.Status.CLOSED)


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _visitor_client(visitor, origin="https://example.com"):
    client = APIClient()
    client.credentials(
        HTTP_X_VISITOR_TOKEN=issue_visitor_token(visitor),
        HTTP_ORIGIN=origin,
    )
    return client


class RateTicketServiceTests(TestCase):
    def test_unfinished_tickets_cannot_be_rated(self):
        for status in UNFINISHED:
            with self.subTest(status=status):
                ticket = TicketFactory(status=status)
                with self.assertRaises(TicketNotResolved):
                    rate_ticket(ticket, 5)
        self.assertFalse(TicketRating.objects.exists())

    def test_resolved_and_closed_tickets_can_be_rated(self):
        for status in FINISHED:
            with self.subTest(status=status):
                ticket = TicketFactory(status=status)
                record = rate_ticket(ticket, 4, "Good")
                self.assertEqual((record.ticket, record.score, record.comment), (ticket, 4, "Good"))

    def test_the_comment_is_optional(self):
        record = rate_ticket(TicketFactory(status=Ticket.Status.RESOLVED), 3)
        self.assertEqual(record.comment, "")

    def test_a_second_rating_is_rejected_and_the_first_is_kept(self):
        ticket = TicketFactory(status=Ticket.Status.RESOLVED)
        rate_ticket(ticket, 5)
        with self.assertRaises(TicketAlreadyRated):
            rate_ticket(ticket, 1)
        self.assertEqual(TicketRating.objects.get(ticket=ticket).score, 5)

    def test_a_lost_race_is_reported_as_already_rated(self):
        ticket = TicketFactory(status=Ticket.Status.RESOLVED)
        TicketRatingFactory(ticket=ticket, score=5)

        class NothingFound:
            def exists(self):
                return False

        with patch.object(TicketRating.objects, "filter", return_value=NothingFound()):
            with self.assertRaises(TicketAlreadyRated):
                rate_ticket(ticket, 1)
        self.assertEqual(TicketRating.objects.get(ticket=ticket).score, 5)


class TicketRatingModelTests(TestCase):
    def test_the_database_rejects_scores_outside_one_to_five(self):
        for score in (0, 6):
            with self.subTest(score=score):
                ticket = TicketFactory(status=Ticket.Status.RESOLVED)
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        TicketRating.objects.create(ticket=ticket, score=score)

    def test_the_database_allows_one_rating_per_ticket(self):
        rating = TicketRatingFactory()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TicketRating.objects.create(ticket=rating.ticket, score=3)

    def test_validation_rejects_bad_scores_and_long_comments(self):
        ticket = TicketFactory(status=Ticket.Status.RESOLVED)
        for payload, field in (
            ({"score": 0}, "score"),
            ({"score": 6}, "score"),
            ({"score": 3, "comment": "x" * 1001}, "comment"),
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(DjangoValidationError) as caught:
                    TicketRating(ticket=ticket, **payload).full_clean()
                self.assertIn(field, caught.exception.message_dict)

    def test_str_shows_the_score_and_the_ticket(self):
        rating = TicketRatingFactory(score=4)
        self.assertEqual(str(rating), f"Rating 4/5 for Ticket #{rating.ticket_id}")

    def test_the_admin_lists_ratings_but_cannot_change_them(self):
        admin_instance = site._registry[TicketRating]
        self.assertIn("score", admin_instance.list_display)
        self.assertFalse(admin_instance.has_change_permission(request=None))


class PortalRatingApiTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.other_customer = UserFactory()
        self.agent = AgentFactory()
        self.admin = AdminFactory()
        self.ticket = TicketFactory(customer=self.customer, status=Ticket.Status.RESOLVED)
        self.url = f"/api/tickets/{self.ticket.id}/rating/"
        self.owner = _client_for(self.customer)

    def _post(self, payload, client=None, url=None):
        return (client or self.owner).post(url or self.url, payload, format="json")

    def _assert_rejected(self, response, field):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn(field, response.data["error"]["details"])
        self.assertFalse(TicketRating.objects.exists())

    def test_the_owner_rates_a_resolved_ticket(self):
        response = self._post({"score": 5, "comment": "Great help"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.data), RATING_KEYS)
        self.assertEqual((response.data["score"], response.data["comment"]), (5, "Great help"))
        stored = TicketRating.objects.get()
        self.assertEqual((stored.ticket, stored.score), (self.ticket, 5))

    def test_the_comment_is_optional_and_may_be_persian(self):
        self.assertEqual(self._post({"score": 4}).data["comment"], "")
        other = TicketFactory(customer=self.customer, status=Ticket.Status.CLOSED)
        response = self._post({"score": 3, "comment": "ممنون از پشتیبانی"}, url=self._url(other))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["comment"], "ممنون از پشتیبانی")

    def _url(self, ticket):
        return f"/api/tickets/{ticket.id}/rating/"

    def test_a_closed_ticket_can_be_rated(self):
        Ticket.objects.filter(pk=self.ticket.pk).update(status=Ticket.Status.CLOSED)
        self.assertEqual(self._post({"score": 2}).status_code, 201)

    def test_a_second_rating_is_rejected(self):
        self._post({"score": 5})
        response = self._post({"score": 1})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"]["code"], "ticket_already_rated")
        self.assertEqual(TicketRating.objects.get().score, 5)

    def test_a_reopened_and_resolved_again_ticket_cannot_be_rated_twice(self):
        self._post({"score": 5})
        Ticket.objects.filter(pk=self.ticket.pk).update(status=Ticket.Status.IN_PROGRESS)
        Ticket.objects.filter(pk=self.ticket.pk).update(status=Ticket.Status.RESOLVED)
        self.assertEqual(self._post({"score": 1}).status_code, 409)

    def test_an_unfinished_ticket_cannot_be_rated(self):
        for status in UNFINISHED:
            with self.subTest(status=status):
                Ticket.objects.filter(pk=self.ticket.pk).update(status=status)
                response = self._post({"score": 5})
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.data["error"]["code"], "ticket_not_resolved")
        self.assertFalse(TicketRating.objects.exists())

    def test_invalid_scores_are_rejected(self):
        for payload in ({}, {"score": 0}, {"score": 6}, {"score": -1}, {"score": "five"}):
            with self.subTest(payload=payload):
                self._assert_rejected(self._post(payload), "score")

    def test_the_comment_has_a_length_limit(self):
        self._assert_rejected(self._post({"score": 3, "comment": "x" * 1001}), "comment")
        self.assertEqual(self._post({"score": 3, "comment": "x" * 1000}).status_code, 201)

    def test_staff_cannot_rate_a_ticket(self):
        for user in (self.agent, self.admin):
            with self.subTest(role=user.role):
                response = self._post({"score": 5}, client=_client_for(user))
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.data["error"]["code"], "permission_denied")
        self.assertFalse(TicketRating.objects.exists())

    def test_another_customer_does_not_even_see_the_ticket(self):
        response = self._post({"score": 5}, client=_client_for(self.other_customer))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(TicketRating.objects.exists())

    def test_unauthenticated_requests_are_rejected(self):
        self.assertEqual(APIClient().post(self.url, {"score": 5}, format="json").status_code, 401)
        self.assertEqual(APIClient().get(self.url).status_code, 401)

    def test_staff_cannot_rate_a_visitor_conversation_either(self):
        ticket = TicketFactory(from_visitor=True, status=Ticket.Status.RESOLVED)
        response = self._post({"score": 5}, client=_client_for(self.agent), url=self._url(ticket))
        self.assertEqual(response.status_code, 403)

    def test_a_deleted_ticket_cannot_be_rated(self):
        self.ticket.delete()
        self.assertEqual(self._post({"score": 5}).status_code, 404)

    def test_the_rating_can_be_read_by_the_owner_and_by_staff(self):
        self.assertEqual(self.owner.get(self.url).status_code, 404)
        self._post({"score": 4, "comment": "ok"})
        for client in (self.owner, _client_for(self.agent), _client_for(self.admin)):
            response = client.get(self.url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(set(response.data), RATING_KEYS)
            self.assertEqual(response.data["score"], 4)

    def test_another_customer_cannot_read_the_rating(self):
        self._post({"score": 4})
        response = _client_for(self.other_customer).get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_ratings_cannot_be_replaced_or_removed(self):
        self._post({"score": 4})
        for method in ("put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.owner, method)(self.url, {"score": 1}, format="json")
                self.assertEqual(response.status_code, 405)
        self.assertEqual(TicketRating.objects.get().score, 4)


class WidgetRatingApiTests(TestCase):
    def setUp(self):
        self.ticket = TicketFactory(from_visitor=True, status=Ticket.Status.RESOLVED)
        self.url = f"/api/widget/conversations/{self.ticket.id}/rating/"
        self.client = _visitor_client(self.ticket.visitor)

    def _post(self, payload, client=None, url=None):
        return (client or self.client).post(url or self.url, payload, format="json")

    def test_a_visitor_rates_their_resolved_conversation(self):
        response = self._post({"score": 5, "comment": "Fast"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.data), RATING_KEYS)
        self.assertEqual(TicketRating.objects.get().ticket, self.ticket)

    def test_a_closed_conversation_can_be_rated(self):
        Ticket.objects.filter(pk=self.ticket.pk).update(status=Ticket.Status.CLOSED)
        self.assertEqual(self._post({"score": 3}).status_code, 201)

    def test_a_second_rating_is_rejected(self):
        self._post({"score": 5})
        response = self._post({"score": 2})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"]["code"], "ticket_already_rated")

    def test_an_unfinished_conversation_cannot_be_rated(self):
        Ticket.objects.filter(pk=self.ticket.pk).update(status=Ticket.Status.IN_PROGRESS)
        response = self._post({"score": 5})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"]["code"], "ticket_not_resolved")

    def test_invalid_scores_are_rejected(self):
        for payload in ({}, {"score": 0}, {"score": 6}):
            with self.subTest(payload=payload):
                response = self._post(payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("score", response.data["error"]["details"])

    def test_the_rating_can_be_read_back(self):
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self._post({"score": 4})
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["score"], 4)

    def test_another_visitor_cannot_reach_the_conversation(self):
        other = _visitor_client(VisitorFactory(site=self.ticket.site))
        self.assertEqual(self._post({"score": 5}, client=other).status_code, 404)
        self.assertEqual(other.get(self.url).status_code, 404)
        self.assertFalse(TicketRating.objects.exists())

    def test_a_visitor_cannot_rate_a_portal_ticket(self):
        portal = TicketFactory(status=Ticket.Status.RESOLVED)
        url = f"/api/widget/conversations/{portal.id}/rating/"
        self.assertEqual(self._post({"score": 5}, url=url).status_code, 404)

    def test_an_unlisted_origin_is_refused(self):
        client = _visitor_client(self.ticket.visitor, origin="https://evil.example")
        self.assertEqual(self._post({"score": 5}, client=client).status_code, 403)
        self.assertFalse(TicketRating.objects.exists())

    def test_a_missing_or_deactivated_token_is_refused(self):
        self.assertEqual(self._post({"score": 5}, client=APIClient()).status_code, 401)
        Site.objects.filter(pk=self.ticket.site_id).update(is_active=False)
        self.assertEqual(self._post({"score": 5}).status_code, 401)

    def test_staff_can_read_a_widget_rating(self):
        self._post({"score": 4})
        response = _client_for(AgentFactory()).get(f"/api/tickets/{self.ticket.id}/rating/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["score"], 4)
