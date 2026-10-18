from django.contrib.admin.sites import site as admin_site
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import (
    AgentFactory,
    SiteFactory,
    TicketFactory,
    UserFactory,
    VisitorFactory,
)
from tickets.models import Ticket, TicketEvent


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


class TicketChannelTests(TestCase):
    def test_a_new_ticket_defaults_to_the_portal_channel_without_site_or_visitor(self):
        ticket = TicketFactory()
        self.assertEqual(ticket.channel, Ticket.Channel.PORTAL)
        self.assertIsNone(ticket.site)
        self.assertIsNone(ticket.visitor)

    def test_the_channels_are_portal_chat_and_offline_form(self):
        self.assertEqual(Ticket.Channel.values, ["portal", "chat", "offline_form"])

    def test_every_channel_can_be_stored(self):
        for channel in Ticket.Channel.values:
            with self.subTest(channel=channel):
                ticket = TicketFactory(channel=channel)
                ticket.refresh_from_db()
                self.assertEqual(ticket.channel, channel)

    def test_an_unknown_channel_fails_validation(self):
        ticket = TicketFactory.build(channel="sms", customer=UserFactory())
        with self.assertRaises(ValidationError) as caught:
            ticket.full_clean(exclude=["customer"])
        self.assertIn("channel", caught.exception.message_dict)

    def test_a_ticket_can_carry_a_site(self):
        site = SiteFactory()
        ticket = TicketFactory(site=site)
        self.assertEqual(list(site.tickets.all()), [ticket])

    def test_a_customer_created_through_the_api_gets_the_portal_channel(self):
        customer = UserFactory()
        response = _client_for(customer).post(
            "/api/tickets/", {"title": "t", "description": "d"}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        ticket = Ticket.objects.get(pk=response.data["id"])
        self.assertEqual(ticket.channel, Ticket.Channel.PORTAL)
        self.assertEqual(ticket.customer, customer)
        self.assertIsNone(ticket.visitor)
        self.assertIsNone(ticket.site)


class TicketOwnerValidationTests(TestCase):
    def test_a_ticket_with_a_customer_only_is_valid(self):
        ticket = TicketFactory()
        ticket.clean()
        ticket.full_clean()

    def test_a_ticket_with_a_visitor_only_is_valid(self):
        ticket = TicketFactory(from_visitor=True)
        ticket.clean()
        ticket.full_clean()

    def test_clean_rejects_neither_owner(self):
        ticket = Ticket(title="t", description="d")
        with self.assertRaises(ValidationError):
            ticket.clean()

    def test_clean_rejects_both_owners(self):
        ticket = Ticket(
            title="t", description="d", customer=UserFactory(), visitor=VisitorFactory()
        )
        with self.assertRaises(ValidationError):
            ticket.clean()

    def test_full_clean_reports_the_owner_error(self):
        ticket = Ticket(title="t", description="d")
        with self.assertRaises(ValidationError) as caught:
            ticket.full_clean()
        self.assertIn("__all__", caught.exception.message_dict)


class TicketOwnerConstraintTests(TestCase):
    def test_db_constraint_rejects_neither_owner(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Ticket.objects.create(title="t", description="d")

    def test_db_constraint_rejects_both_owners(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Ticket.objects.create(
                    title="t",
                    description="d",
                    customer=UserFactory(),
                    visitor=VisitorFactory(),
                )

    def test_db_constraint_accepts_a_customer_only(self):
        ticket = Ticket.objects.create(title="t", description="d", customer=UserFactory())
        self.assertIsNotNone(ticket.pk)

    def test_db_constraint_accepts_a_visitor_only(self):
        visitor = VisitorFactory()
        ticket = Ticket.objects.create(
            title="t",
            description="d",
            visitor=visitor,
            site=visitor.site,
            channel=Ticket.Channel.CHAT,
        )
        self.assertIsNotNone(ticket.pk)

    def test_db_constraint_rejects_removing_the_only_owner(self):
        ticket = TicketFactory()
        ticket.customer = None
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ticket.save()

    def test_db_constraint_rejects_adding_a_second_owner(self):
        ticket = TicketFactory(from_visitor=True)
        ticket.customer = UserFactory()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ticket.save()

    def test_db_constraint_applies_to_bulk_updates(self):
        ticket = TicketFactory()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Ticket.objects.filter(pk=ticket.pk).update(customer=None)
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.customer)

    def test_the_owner_can_move_from_a_visitor_to_a_customer_in_one_save(self):
        ticket = TicketFactory(from_visitor=True)
        customer = UserFactory()
        ticket.visitor = None
        ticket.customer = customer
        ticket.save()
        ticket.refresh_from_db()
        self.assertEqual(ticket.customer, customer)
        self.assertIsNone(ticket.visitor)


class TicketOwnerProtectionTests(TestCase):
    def test_a_site_with_tickets_cannot_be_deleted(self):
        site = SiteFactory()
        TicketFactory(site=site)
        with self.assertRaises(ProtectedError):
            site.delete()

    def test_a_customer_with_tickets_is_still_protected(self):
        ticket = TicketFactory()
        with self.assertRaises(ProtectedError):
            ticket.customer.delete()


class TicketFactoryVisitorTraitTests(TestCase):
    def test_the_trait_builds_a_chat_ticket_owned_by_a_visitor(self):
        ticket = TicketFactory(from_visitor=True)
        self.assertIsNone(ticket.customer)
        self.assertIsNotNone(ticket.visitor)
        self.assertEqual(ticket.site, ticket.visitor.site)
        self.assertEqual(ticket.channel, Ticket.Channel.CHAT)

    def test_the_trait_accepts_an_existing_visitor(self):
        visitor = VisitorFactory()
        ticket = TicketFactory(from_visitor=True, visitor=visitor)
        self.assertEqual(ticket.visitor, visitor)
        self.assertEqual(ticket.site, visitor.site)

    def test_the_channel_can_be_overridden(self):
        ticket = TicketFactory(from_visitor=True, channel=Ticket.Channel.OFFLINE_FORM)
        self.assertEqual(ticket.channel, Ticket.Channel.OFFLINE_FORM)


class VisitorTicketApiTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.agent = AgentFactory()
        self.own = TicketFactory(customer=self.customer)
        self.chat = TicketFactory(from_visitor=True)

    def test_staff_see_visitor_tickets_with_no_customer(self):
        response = _client_for(self.agent).get("/api/tickets/")
        self.assertEqual(response.status_code, 200)
        rows = {row["id"]: row for row in response.data["results"]}
        self.assertEqual(set(rows), {self.own.id, self.chat.id})
        self.assertIsNone(rows[self.chat.id]["customer"])
        self.assertEqual(rows[self.own.id]["customer"], self.customer.id)

    def test_staff_can_retrieve_a_visitor_ticket(self):
        response = _client_for(self.agent).get(f"/api/tickets/{self.chat.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["customer"])

    def test_customers_never_see_visitor_tickets(self):
        client = _client_for(self.customer)
        listing = client.get("/api/tickets/")
        self.assertEqual([row["id"] for row in listing.data["results"]], [self.own.id])
        self.assertEqual(client.get(f"/api/tickets/{self.chat.id}/").status_code, 404)
        self.assertEqual(client.get(f"/api/tickets/{self.chat.id}/comments/").status_code, 404)

    def test_staff_can_work_a_visitor_ticket_and_the_event_is_written(self):
        response = _client_for(self.agent).patch(
            f"/api/tickets/{self.chat.id}/",
            {"status": Ticket.Status.IN_PROGRESS, "assignee": self.agent.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        events = TicketEvent.objects.filter(ticket=self.chat)
        self.assertEqual({event.field_changed for event in events}, {"status", "assignee"})
        self.assertEqual({event.actor_id for event in events}, {self.agent.id})

    def test_staff_can_comment_on_a_visitor_ticket(self):
        response = _client_for(self.agent).post(
            f"/api/tickets/{self.chat.id}/comments/", {"body": "Hello"}, format="json"
        )
        self.assertEqual(response.status_code, 201)


class TicketAdminOwnerTests(TestCase):
    def test_the_admin_shows_and_filters_by_channel_and_visitor(self):
        admin_instance = admin_site._registry[Ticket]
        self.assertIn("channel", admin_instance.list_display)
        self.assertIn("visitor", admin_instance.list_display)
        self.assertIn("channel", admin_instance.list_filter)

    def test_the_admin_treats_ownership_fields_as_read_only(self):
        admin_instance = admin_site._registry[Ticket]
        self.assertIn("visitor", admin_instance.readonly_fields)
        self.assertIn("site", admin_instance.readonly_fields)
        self.assertIn("customer", admin_instance.readonly_fields)

    def test_the_admin_queryset_includes_visitor_tickets(self):
        ticket = TicketFactory(from_visitor=True)
        admin_instance = admin_site._registry[Ticket]
        self.assertIn(ticket, admin_instance.get_queryset(None))
