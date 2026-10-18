from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.search import ARABIC_YEH, PERSIAN_YEH
from core.tests.factories import AdminFactory, AgentFactory, TagFactory, TicketFactory, UserFactory
from tickets.events import TAG_FIELD, record_event, tag_changes
from tickets.models import Tag, Ticket, TicketEvent

URL = "/api/tags/"
TAG_KEYS = {"id", "name", "color", "created_at", "updated_at"}

ROLES = ["unauthenticated", "customer", "agent", "admin"]
EXPECTED = {
    "list": (401, 403, 200, 200),
    "retrieve": (401, 403, 200, 200),
    "create": (401, 403, 403, 201),
    "update": (401, 403, 403, 200),
    "delete": (401, 403, 403, 204),
    "put": (401, 403, 403, 405),
}
MATRIX = [
    (role, action, statuses[index])
    for action, statuses in EXPECTED.items()
    for index, role in enumerate(ROLES)
]


def _client_for(user, **defaults):
    client = APIClient(**defaults)
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


@pytest.mark.django_db
@pytest.mark.parametrize("role,action,expected_status", MATRIX)
def test_tag_permission_matrix(role, action, expected_status):
    users = {"customer": UserFactory(), "agent": AgentFactory(), "admin": AdminFactory()}
    target = TagFactory()
    detail_url = f"{URL}{target.id}/"
    client = APIClient()
    if role != "unauthenticated":
        refresh = RefreshToken.for_user(users[role])
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    if action == "list":
        response = client.get(URL)
    elif action == "retrieve":
        response = client.get(detail_url)
    elif action == "create":
        response = client.post(URL, {"name": "matrix"}, format="json")
    elif action == "update":
        response = client.patch(detail_url, {"name": "renamed"}, format="json")
    elif action == "delete":
        response = client.delete(detail_url)
    elif action == "put":
        response = client.put(detail_url, {"name": "replaced"}, format="json")

    assert response.status_code == expected_status


class TagModelTests(TestCase):
    def test_defaults_and_str(self):
        tag = Tag.objects.create(name="Bug")
        self.assertEqual(tag.color, Tag.Color.GRAY)
        self.assertEqual(str(tag), "Bug")

    def test_tags_are_ordered_by_name(self):
        second = TagFactory(name="b")
        first = TagFactory(name="a")
        self.assertEqual(list(Tag.objects.all()), [first, second])

    def test_names_are_unique_ignoring_case_in_the_database(self):
        TagFactory(name="Bug")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Tag.objects.create(name="bug")

    def test_clean_normalizes_the_name(self):
        tag = Tag(name=f"  Bug{ARABIC_YEH}  ")
        tag.clean()
        self.assertEqual(tag.name, f"Bug{PERSIAN_YEH}")

    def test_an_unknown_color_fails_validation(self):
        with self.assertRaises(ValidationError) as caught:
            Tag(name="x", color="magenta").full_clean()
        self.assertIn("color", caught.exception.message_dict)

    def test_the_admin_registers_tags_with_search(self):
        self.assertIn("name", site._registry[Tag].search_fields)


class TagApiTests(TestCase):
    def setUp(self):
        self.admin = AdminFactory()
        self.client = _client_for(self.admin)

    def _create(self, **overrides):
        payload = {"name": "Billing"}
        payload.update(overrides)
        return self.client.post(URL, payload, format="json")

    def _assert_rejected(self, response, field):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn(field, response.data["error"]["details"])

    def test_a_tag_is_created_with_the_default_color(self):
        response = self._create()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.data), TAG_KEYS)
        self.assertEqual(response.data["color"], "gray")
        self.assertEqual(Tag.objects.get().name, "Billing")

    def test_a_color_can_be_chosen(self):
        self.assertEqual(self._create(color="red").data["color"], "red")
        self._assert_rejected(self._create(name="Other", color="magenta"), "color")

    def test_names_are_normalized(self):
        response = self._create(name=f"  Bug   {ARABIC_YEH}  ")
        self.assertEqual(response.data["name"], f"Bug {PERSIAN_YEH}")

    def test_names_must_be_unique_ignoring_case_and_arabic_variants(self):
        TagFactory(name="Billing")
        TagFactory(name=f"a{PERSIAN_YEH}")
        for name in ("billing", "BILLING", f"a{ARABIC_YEH}"):
            with self.subTest(name=name):
                self._assert_rejected(self._create(name=name), "name")
        self.assertEqual(Tag.objects.count(), 2)

    def test_blank_and_overlong_names_are_rejected(self):
        for name in ("", "   ", "x" * 51):
            with self.subTest(name=name):
                self._assert_rejected(self._create(name=name), "name")

    def test_the_list_is_not_paginated_and_sorted_by_name(self):
        for name in ("c", "a", "b"):
            TagFactory(name=name)
        response = self.client.get(URL)
        self.assertEqual([row["name"] for row in response.data], ["a", "b", "c"])

    def test_a_tag_can_be_renamed_and_keep_its_own_name(self):
        tag = TagFactory(name="Billing")
        renamed = self.client.patch(f"{URL}{tag.id}/", {"name": "Invoices"}, format="json")
        self.assertEqual(renamed.data["name"], "Invoices")
        same = self.client.patch(f"{URL}{tag.id}/", {"name": "invoices"}, format="json")
        self.assertEqual(same.status_code, 200)

    def test_a_tag_cannot_take_another_tags_name(self):
        TagFactory(name="Billing")
        tag = TagFactory(name="Other")
        response = self.client.patch(f"{URL}{tag.id}/", {"name": "billing"}, format="json")
        self._assert_rejected(response, "name")

    def test_unknown_tag_returns_404(self):
        self.assertEqual(self.client.get(f"{URL}999999/").status_code, 404)


class TagDeletionTests(TestCase):
    def setUp(self):
        self.admin = AdminFactory()
        self.client = _client_for(self.admin)

    def test_deleting_a_tag_writes_an_event_for_every_ticket_that_had_it(self):
        tag = TagFactory(name="Billing")
        live = TicketFactory(tags=[tag])
        hidden = TicketFactory(tags=[tag])
        hidden.delete()
        other = TicketFactory()

        response = self.client.delete(f"{URL}{tag.id}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Tag.objects.filter(pk=tag.pk).exists())
        events = TicketEvent.objects.filter(field_changed="tag")
        self.assertEqual({event.ticket_id for event in events}, {live.id, hidden.id})
        for event in events:
            self.assertEqual((event.old_value, event.new_value), ("Billing", ""))
            self.assertEqual(event.actor, self.admin)
        self.assertEqual(live.tags.count(), 0)
        self.assertFalse(TicketEvent.objects.filter(ticket=other).exists())

    def test_a_failure_while_writing_events_keeps_the_tag(self):
        tag = TagFactory()
        ticket = TicketFactory(tags=[tag])
        client = _client_for(self.admin, raise_request_exception=False)
        with patch(
            "tickets.tags.TicketEvent.objects.bulk_create", side_effect=RuntimeError("boom")
        ):
            response = client.delete(f"{URL}{tag.id}/")
        self.assertEqual(response.status_code, 500)
        self.assertTrue(Tag.objects.filter(pk=tag.pk).exists())
        self.assertEqual(ticket.tags.count(), 1)
        self.assertFalse(TicketEvent.objects.exists())


class TicketTaggingTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.agent = AgentFactory()
        self.staff = _client_for(self.agent)
        self.owner = _client_for(self.customer)

    def _patch(self, ticket, payload, client=None):
        return (client or self.staff).patch(f"/api/tickets/{ticket.id}/", payload, format="json")

    def _tag_events(self, ticket):
        return TicketEvent.objects.filter(ticket=ticket, field_changed="tag").order_by("id")

    def test_staff_can_tag_a_ticket_and_each_tag_writes_an_event(self):
        ticket = TicketFactory(customer=self.customer)
        first, second = TagFactory(name="alpha"), TagFactory(name="bravo")
        response = self._patch(ticket, {"tags": [first.id, second.id]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sorted(response.data["tags"]), sorted([first.id, second.id]))
        events = self._tag_events(ticket)
        self.assertEqual(
            {(e.old_value, e.new_value) for e in events}, {("", "alpha"), ("", "bravo")}
        )
        self.assertEqual({e.actor_id for e in events}, {self.agent.id})

    def test_adding_and_removing_tags_writes_one_event_per_change(self):
        a, b, c = TagFactory(name="a"), TagFactory(name="b"), TagFactory(name="c")
        ticket = TicketFactory(customer=self.customer, tags=[a, b])
        self._patch(ticket, {"tags": [b.id, c.id]})
        values = list(self._tag_events(ticket).values_list("old_value", "new_value"))
        self.assertEqual(values, [("a", ""), ("", "c")])
        self.assertEqual({tag.id for tag in ticket.tags.all()}, {b.id, c.id})

    def test_unchanged_tags_write_no_event(self):
        tag = TagFactory()
        ticket = TicketFactory(customer=self.customer, tags=[tag])
        self._patch(ticket, {"tags": [tag.id]})
        self.assertFalse(self._tag_events(ticket).exists())

    def test_an_empty_list_removes_every_tag(self):
        tags = TagFactory.create_batch(2)
        ticket = TicketFactory(customer=self.customer, tags=tags)
        response = self._patch(ticket, {"tags": []})
        self.assertEqual(response.data["tags"], [])
        self.assertEqual(self._tag_events(ticket).count(), 2)

    def test_duplicate_tag_ids_are_collapsed(self):
        tag = TagFactory()
        ticket = TicketFactory(customer=self.customer)
        response = self._patch(ticket, {"tags": [tag.id, tag.id]})
        self.assertEqual(response.data["tags"], [tag.id])
        self.assertEqual(self._tag_events(ticket).count(), 1)

    def test_a_ticket_can_have_at_most_ten_tags(self):
        ticket = TicketFactory(customer=self.customer)
        tags = TagFactory.create_batch(11)
        response = self._patch(ticket, {"tags": [tag.id for tag in tags]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("tags", response.data["error"]["details"])
        ok = self._patch(ticket, {"tags": [tag.id for tag in tags[:10]]})
        self.assertEqual(ok.status_code, 200)

    def test_unknown_tags_are_rejected(self):
        ticket = TicketFactory(customer=self.customer)
        response = self._patch(ticket, {"tags": [999999]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("tags", response.data["error"]["details"])

    def test_tags_can_be_set_when_staff_create_a_ticket(self):
        tag = TagFactory(name="mobile")
        response = self.staff.post(
            "/api/tickets/", {"title": "t", "description": "d", "tags": [tag.id]}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        ticket = Ticket.objects.get(pk=response.data["id"])
        event = self._tag_events(ticket).get()
        self.assertEqual(
            (event.old_value, event.new_value, event.actor), ("", "mobile", self.agent)
        )

    def test_customers_cannot_send_tags(self):
        tag = TagFactory()
        created = self.owner.post(
            "/api/tickets/", {"title": "t", "description": "d", "tags": [tag.id]}, format="json"
        )
        self.assertEqual(created.status_code, 403)
        ticket = TicketFactory(customer=self.customer)
        updated = self._patch(ticket, {"tags": [tag.id]}, client=self.owner)
        self.assertEqual(updated.status_code, 403)
        self.assertEqual(ticket.tags.count(), 0)

    def test_customers_never_see_tags_in_ticket_responses(self):
        ticket = TicketFactory(customer=self.customer, tags=[TagFactory()])
        detail = self.owner.get(f"/api/tickets/{ticket.id}/")
        listing = self.owner.get("/api/tickets/")
        self.assertNotIn("tags", detail.data)
        self.assertNotIn("tags", listing.data["results"][0])
        self.assertIn("tags", self.staff.get(f"/api/tickets/{ticket.id}/").data)


class TagEventVisibilityTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.staff = _client_for(AgentFactory())
        self.owner = _client_for(self.customer)
        self.ticket = TicketFactory(customer=self.customer)
        self.tag = TagFactory(name="secret")
        response = self.staff.patch(
            f"/api/tickets/{self.ticket.id}/",
            {"tags": [self.tag.id], "status": Ticket.Status.IN_PROGRESS},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def _fields(self, client):
        response = client.get(f"/api/tickets/{self.ticket.id}/events/")
        self.assertEqual(response.status_code, 200)
        return sorted(row["field_changed"] for row in response.data)

    def test_customers_never_see_tag_events(self):
        self.assertEqual(self._fields(self.owner), ["status"])

    def test_staff_see_tag_events(self):
        self.assertEqual(self._fields(self.staff), ["status", "tag"])

    def test_events_written_by_deleting_a_tag_are_hidden_from_customers_too(self):
        admin = _client_for(AdminFactory())
        self.assertEqual(admin.delete(f"{URL}{self.tag.id}/").status_code, 204)
        self.assertEqual(self._fields(self.owner), ["status"])
        self.assertEqual(self._fields(self.staff), ["status", "tag", "tag"])


class TagChangesTests(SimpleTestCase):
    def _tags(self, *pairs):
        return [SimpleNamespace(pk=pk, name=name) for pk, name in pairs]

    def test_identical_sets_have_no_changes(self):
        tags = self._tags((1, "a"), (2, "b"))
        self.assertEqual(tag_changes(tags, tags), [])

    def test_added_tags_are_reported_by_name_in_order(self):
        changes = tag_changes([], self._tags((1, "b"), (2, "a")))
        self.assertEqual(changes, [(TAG_FIELD, "", "a"), (TAG_FIELD, "", "b")])

    def test_removed_tags_are_reported_by_name_in_order(self):
        changes = tag_changes(self._tags((1, "b"), (2, "a")), [])
        self.assertEqual(changes, [(TAG_FIELD, "a", ""), (TAG_FIELD, "b", "")])

    def test_removals_come_before_additions(self):
        old = self._tags((1, "a"), (2, "b"))
        new = self._tags((2, "b"), (3, "c"))
        self.assertEqual(tag_changes(old, new), [(TAG_FIELD, "a", ""), (TAG_FIELD, "", "c")])

    def test_a_renamed_tag_is_not_a_change(self):
        self.assertEqual(tag_changes(self._tags((1, "old")), self._tags((1, "new"))), [])


class RecordEventPublishingTests(TestCase):
    def test_tag_and_assignee_events_are_staff_only(self):
        ticket = TicketFactory()
        with patch("tickets.events.publish") as publish:
            record_event(ticket, None, TAG_FIELD, "", "x")
            record_event(ticket, None, "assignee", "", "someone")
            record_event(ticket, None, "status", "open", "in_progress")
            record_event(ticket, None, "channel", "chat", "offline_form")
        flags = [call.kwargs["staff_only"] for call in publish.call_args_list]
        self.assertEqual(flags, [True, True, False, False])

    def test_the_event_is_stored_and_published_with_its_values(self):
        ticket = TicketFactory()
        with patch("tickets.events.publish") as publish:
            event = record_event(ticket, None, TAG_FIELD, "", "x")
        self.assertEqual(TicketEvent.objects.get(), event)
        args = publish.call_args.args
        self.assertEqual(args[0], "ticket.event")
        self.assertEqual(args[1:3], (event.pk, ticket.pk))
        self.assertEqual(args[3], {"field_changed": TAG_FIELD, "old_value": "", "new_value": "x"})


class TagFilterTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.staff = _client_for(AgentFactory())
        self.owner = _client_for(self.customer)
        self.billing = TagFactory(name="billing")
        self.bug = TagFactory(name="bug")
        self.only_billing = TicketFactory(customer=self.customer, tags=[self.billing])
        self.both = TicketFactory(customer=self.customer, tags=[self.billing, self.bug])
        self.only_bug = TicketFactory(tags=[self.bug])
        self.untagged = TicketFactory(customer=self.customer)

    def _ids(self, client, query):
        response = client.get(f"/api/tickets/{query}")
        self.assertEqual(response.status_code, 200)
        return {row["id"] for row in response.data["results"]}

    def test_staff_filter_by_tag(self):
        self.assertEqual(
            self._ids(self.staff, f"?tag={self.billing.id}"),
            {self.only_billing.id, self.both.id},
        )
        self.assertEqual(
            self._ids(self.staff, f"?tag={self.bug.id}"), {self.both.id, self.only_bug.id}
        )

    def test_a_ticket_with_several_tags_is_listed_once(self):
        response = self.staff.get(f"/api/tickets/?tag={self.bug.id}")
        ids = [row["id"] for row in response.data["results"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_unknown_tag_returns_an_empty_page(self):
        self.assertEqual(self._ids(self.staff, "?tag=999999"), set())

    def test_non_numeric_tags_are_rejected(self):
        for value in ("abc", "-1", "1.5", "1;2"):
            with self.subTest(value=value):
                response = self.staff.get("/api/tickets/", {"tag": value})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["error"]["code"], "validation_error")
                self.assertIn("tag", response.data["error"]["details"])

    def test_an_empty_tag_parameter_is_ignored(self):
        self.assertEqual(self._ids(self.staff, "?tag="), {t.id for t in Ticket.objects.all()})

    def test_the_tag_filter_combines_with_other_filters(self):
        Ticket.objects.filter(pk=self.both.pk).update(status=Ticket.Status.IN_PROGRESS)
        query = f"?tag={self.billing.id}&status=in_progress"
        self.assertEqual(self._ids(self.staff, query), {self.both.id})

    def test_deleted_tickets_are_not_found_by_tag(self):
        self.only_bug.delete()
        self.assertEqual(self._ids(self.staff, f"?tag={self.bug.id}"), {self.both.id})

    def test_customers_get_nothing_even_for_their_own_tagged_tickets(self):
        self.assertEqual(self._ids(self.owner, f"?tag={self.billing.id}"), set())
        self.assertEqual(
            self._ids(self.owner, ""), {self.only_billing.id, self.both.id, self.untagged.id}
        )

    def test_admins_can_filter_by_tag(self):
        admin = _client_for(AdminFactory())
        self.assertEqual(
            self._ids(admin, f"?tag={self.billing.id}"), {self.only_billing.id, self.both.id}
        )

    def test_the_tag_survives_pagination(self):
        tagged = TicketFactory.create_batch(25, tags=[self.billing])
        seen = []
        response = self.staff.get(f"/api/tickets/?tag={self.billing.id}")
        while True:
            self.assertEqual(response.status_code, 200)
            seen.extend(row["id"] for row in response.data["results"])
            if not response.data["next"]:
                break
            response = self.staff.get(response.data["next"])
        expected = {ticket.id for ticket in tagged} | {self.only_billing.id, self.both.id}
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(set(seen), expected)
