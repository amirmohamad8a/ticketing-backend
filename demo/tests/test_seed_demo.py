from collections import Counter
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from rest_framework.test import APIClient

from accounts.models import User
from chat.models import Site, Visitor
from demo.demo import (
    ADMIN_USERNAME,
    AGENT_USERNAME,
    CANNED_REPLIES,
    CHAT_TICKETS,
    CUSTOMER_USERNAME,
    DEMO_PASSWORD,
    PORTAL_TICKETS,
    SITE_KEY,
    TAGS,
)
from tickets.models import CannedReply, Comment, Tag, Ticket, TicketEvent, TicketRating
from tickets.validators import validate_shortcut

SPECS = (*PORTAL_TICKETS, *CHAT_TICKETS)


def _seed():
    out = StringIO()
    call_command("seed_demo", force=True, stdout=out)
    return out.getvalue()


def _counts():
    return (
        User.objects.count(),
        Ticket.all_objects.count(),
        Comment.objects.count(),
        TicketEvent.objects.count(),
        Tag.objects.count(),
        CannedReply.objects.count(),
        Site.objects.count(),
        Visitor.objects.count(),
        TicketRating.objects.count(),
    )


def _timeline(spec):
    return sorted(spec["timeline"], key=lambda item: item[0])


def _ticket_for(spec):
    if "title" in spec:
        return Ticket.objects.get(title=spec["title"], customer__username=CUSTOMER_USERNAME)
    return Ticket.objects.get(visitor__name=spec["visitor"], site__key=SITE_KEY)


def _final_status(spec):
    status = Ticket.Status.OPEN
    for _minutes, kind, *args in _timeline(spec):
        if kind == "status":
            status = args[0]
    return status


def _items(spec, kind):
    return [item for item in spec["timeline"] if item[1] == kind]


def _login_client(username):
    response = APIClient().post("/api/token/", {"username": username, "password": DEMO_PASSWORD})
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
    return client


class SeedDemoDataTests(TestCase):
    def test_creates_demo_users_without_email_or_elevated_flags(self):
        _seed()
        customer = User.objects.get(username=CUSTOMER_USERNAME)
        agent = User.objects.get(username=AGENT_USERNAME)
        self.assertEqual(customer.role, User.Role.CUSTOMER)
        self.assertEqual(agent.role, User.Role.AGENT)
        admin = User.objects.get(username=ADMIN_USERNAME)
        self.assertEqual(admin.role, User.Role.ADMIN)
        for user in (customer, agent, admin):
            self.assertEqual(user.email, "")
            self.assertTrue(user.check_password(DEMO_PASSWORD))
            self.assertFalse(user.is_staff)
            self.assertFalse(user.is_superuser)

    def test_the_command_reports_how_many_tickets_are_new(self):
        self.assertIn(f"{len(SPECS)} new ticket(s)", _seed())
        self.assertIn("0 new ticket(s)", _seed())

    def test_creates_the_demo_site(self):
        _seed()
        site = Site.objects.get(key=SITE_KEY)
        self.assertTrue(site.is_active)
        self.assertTrue(site.allowed_origins)
        self.assertTrue(site.greeting)
        self.assertEqual(site.position, Site.Position.BOTTOM_LEFT)
        site.full_clean()

    def test_creates_tags_and_canned_replies(self):
        _seed()
        self.assertEqual(
            set(Tag.objects.values_list("name", "color")), {(name, color) for name, color in TAGS}
        )
        shortcuts = set(CannedReply.objects.values_list("shortcut", flat=True))
        self.assertEqual(shortcuts, {shortcut for shortcut, _title, _body in CANNED_REPLIES})
        for shortcut in shortcuts:
            validate_shortcut(shortcut)

    def test_creates_portal_and_chat_tickets_with_the_right_owners_and_channels(self):
        _seed()
        for spec in PORTAL_TICKETS:
            ticket = _ticket_for(spec)
            self.assertEqual(ticket.channel, Ticket.Channel.PORTAL)
            self.assertIsNone(ticket.visitor)
            self.assertEqual(ticket.priority, spec["priority"])
        for spec in CHAT_TICKETS:
            ticket = _ticket_for(spec)
            offline = bool(_items(spec, "offline"))
            expected = Ticket.Channel.OFFLINE_FORM if offline else Ticket.Channel.CHAT
            self.assertEqual(ticket.channel, expected)
            self.assertIsNone(ticket.customer)
            self.assertEqual(ticket.site.key, SITE_KEY)

    def test_visitors_carry_the_contact_details_of_their_spec(self):
        _seed()
        self.assertEqual(Visitor.objects.count(), len(CHAT_TICKETS))
        for spec in CHAT_TICKETS:
            visitor = Visitor.objects.get(site__key=SITE_KEY, name=spec["visitor"])
            self.assertEqual(visitor.phone, spec.get("phone", ""))
            self.assertEqual(visitor.email, spec.get("email", ""))

    def test_final_status_and_assignee_follow_the_timeline(self):
        _seed()
        agent = User.objects.get(username=AGENT_USERNAME)
        for spec in SPECS:
            ticket = _ticket_for(spec)
            self.assertEqual(ticket.status, _final_status(spec))
            if _items(spec, "assign"):
                self.assertEqual(ticket.assignee, agent)
            else:
                self.assertIsNone(ticket.assignee)

    def test_status_events_form_a_legal_chain_ending_at_the_current_status(self):
        _seed()
        for spec in SPECS:
            ticket = _ticket_for(spec)
            previous = Ticket.Status.OPEN
            events = ticket.events.filter(field_changed="status").order_by("id")
            for event in events:
                self.assertEqual(event.old_value, previous)
                self.assertIn(event.new_value, Ticket.STATUS_TRANSITIONS[previous])
                previous = event.new_value
            self.assertEqual(ticket.status, previous)

    def test_comments_match_the_timeline_including_internal_notes(self):
        _seed()
        messages = sum(len(_items(spec, "message")) for spec in SPECS)
        offline = sum(len(_items(spec, "offline")) for spec in SPECS)
        self.assertEqual(Comment.objects.count(), messages + offline)
        internal = sum(
            1 for spec in SPECS for item in _items(spec, "message") if len(item) > 4 and item[4]
        )
        self.assertGreater(internal, 0)
        self.assertEqual(Comment.objects.filter(is_internal=True).count(), internal)
        self.assertEqual(Comment.objects.filter(kind=Comment.Kind.SYSTEM).count(), offline)

    def test_offline_conversions_leave_a_channel_event(self):
        _seed()
        for spec in CHAT_TICKETS:
            if not _items(spec, "offline"):
                continue
            event = _ticket_for(spec).events.get(field_changed="channel")
            self.assertEqual(event.old_value, Ticket.Channel.CHAT)
            self.assertEqual(event.new_value, Ticket.Channel.OFFLINE_FORM)

    def test_tags_and_their_audit_events_match_the_timeline(self):
        _seed()
        for spec in SPECS:
            ticket = _ticket_for(spec)
            expected = {item[2] for item in _items(spec, "tag")}
            self.assertEqual({tag.name for tag in ticket.tags.all()}, expected)
            events = ticket.events.filter(field_changed="tag")
            self.assertEqual({event.new_value for event in events}, expected)
            self.assertEqual(events.count(), len(expected))

    def test_first_response_is_the_first_public_agent_reply(self):
        _seed()
        for spec in SPECS:
            ticket = _ticket_for(spec)
            reply = (
                ticket.comments.filter(author__username=AGENT_USERNAME, is_internal=False)
                .order_by("created_at", "id")
                .first()
            )
            if reply is None:
                self.assertIsNone(ticket.first_response_at)
            else:
                self.assertEqual(ticket.first_response_at, reply.created_at)

    def test_resolved_at_marks_the_first_time_the_ticket_was_finished(self):
        _seed()
        for spec in SPECS:
            ticket = _ticket_for(spec)
            if ticket.status in Ticket.FINISHED_STATUSES:
                resolved = ticket.events.filter(
                    field_changed="status", new_value=Ticket.Status.RESOLVED
                ).order_by("id")
                self.assertEqual(ticket.resolved_at, resolved.first().created_at)
            else:
                self.assertIsNone(ticket.resolved_at)

    def test_ratings_match_the_timeline_and_sit_on_finished_tickets(self):
        _seed()
        expected = {(item[2], item[3]) for spec in SPECS for item in _items(spec, "rating")}
        stored = set(TicketRating.objects.values_list("score", "comment"))
        self.assertEqual(stored, expected)
        for rating in TicketRating.objects.select_related("ticket"):
            self.assertIn(rating.ticket.status, Ticket.FINISHED_STATUSES)

    def test_nothing_is_dated_in_the_future_and_ages_match_the_specs(self):
        before = timezone.now()
        _seed()
        after = timezone.now()
        for spec in SPECS:
            ticket = _ticket_for(spec)
            self.assertGreaterEqual(ticket.created_at, before - spec["age"])
            self.assertLessEqual(ticket.created_at, after - spec["age"])
        self.assertFalse(Comment.objects.filter(created_at__gt=after).exists())
        self.assertFalse(TicketEvent.objects.filter(created_at__gt=after).exists())

    def test_ticket_status_spread_is_derived_from_the_specs(self):
        _seed()
        expected = Counter(_final_status(spec) for spec in SPECS)
        stored = Counter(Ticket.objects.values_list("status", flat=True))
        self.assertEqual(stored, expected)


class SeedDemoIdempotencyTests(TestCase):
    def test_running_twice_creates_no_duplicates(self):
        _seed()
        first = _counts()
        _seed()
        self.assertEqual(_counts(), first)

    def test_rerun_restores_a_deleted_comment_without_duplicating_the_rest(self):
        _seed()
        first = _counts()
        Comment.objects.first().delete()
        _seed()
        self.assertEqual(_counts(), first)

    def test_rerun_restores_a_deleted_canned_reply(self):
        _seed()
        first = _counts()
        CannedReply.objects.filter(shortcut=CANNED_REPLIES[0][0]).delete()
        _seed()
        self.assertEqual(_counts(), first)

    def test_rerun_does_not_replay_the_history_of_an_existing_ticket(self):
        _seed()
        spec = PORTAL_TICKETS[0]
        ticket = _ticket_for(spec)
        Ticket.objects.filter(pk=ticket.pk).update(status=Ticket.Status.RESOLVED)
        first = _counts()
        _seed()
        self.assertEqual(_counts(), first)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.RESOLVED)

    def test_rerun_does_not_reset_an_existing_users_password(self):
        _seed()
        user = User.objects.get(username=CUSTOMER_USERNAME)
        user.set_password("changed-pass-1")
        user.save()
        _seed()
        user.refresh_from_db()
        self.assertTrue(user.check_password("changed-pass-1"))

    def test_rerun_restores_a_soft_deleted_ticket(self):
        _seed()
        ticket = _ticket_for(PORTAL_TICKETS[1])
        ticket.delete()
        _seed()
        self.assertEqual(Ticket.all_objects.count(), len(SPECS))
        self.assertFalse(Ticket.all_objects.get(pk=ticket.pk).is_deleted)


class SeedDemoApiTests(TestCase):
    def setUp(self):
        _seed()

    def test_every_demo_user_can_sign_in(self):
        client = APIClient()
        for username in (CUSTOMER_USERNAME, AGENT_USERNAME, ADMIN_USERNAME):
            with self.subTest(username=username):
                response = client.post(
                    "/api/token/", {"username": username, "password": DEMO_PASSWORD}
                )
                self.assertEqual(response.status_code, 200)

    def test_demo_customer_sees_only_own_tickets_and_no_internal_comments(self):
        client = _login_client(CUSTOMER_USERNAME)
        response = client.get("/api/tickets/")
        self.assertEqual(len(response.data["results"]), len(PORTAL_TICKETS))
        for row in response.data["results"]:
            self.assertNotIn("tags", row)
            comments = client.get(f"/api/tickets/{row['id']}/comments/")
            self.assertEqual(comments.status_code, 200)
            self.assertFalse(any(comment["is_internal"] for comment in comments.data))

    def test_demo_agent_sees_every_ticket_and_every_internal_comment(self):
        client = _login_client(AGENT_USERNAME)
        response = client.get("/api/tickets/")
        self.assertEqual(len(response.data["results"]), len(SPECS))
        internal_seen = 0
        for ticket in Ticket.objects.all():
            comments = client.get(f"/api/tickets/{ticket.id}/comments/")
            internal_seen += sum(1 for comment in comments.data if comment["is_internal"])
        self.assertEqual(internal_seen, Comment.objects.filter(is_internal=True).count())

    def test_stats_reflect_the_seeded_tickets_and_ratings(self):
        client = _login_client(AGENT_USERNAME)
        response = client.get("/api/stats/")
        self.assertEqual(response.status_code, 200)
        scores = [item[2] for spec in SPECS for item in _items(spec, "rating")]
        self.assertEqual(response.data["tickets_total"], len(SPECS))
        self.assertEqual(response.data["ratings_total"], len(scores))
        self.assertEqual(response.data["average_rating"], round(sum(scores) / len(scores), 2))
        self.assertIsNotNone(response.data["average_first_response_seconds"])

    def test_persian_search_finds_the_matching_chat_and_skips_the_others(self):
        client = _login_client(AGENT_USERNAME)
        response = client.get("/api/tickets/", {"search": "سفارش"})
        ids = {ticket["id"] for ticket in response.data["results"]}
        self.assertIn(_ticket_for(CHAT_TICKETS[0]).id, ids)
        self.assertNotIn(_ticket_for(CHAT_TICKETS[2]).id, ids)

    def test_seeded_tickets_are_not_overdue_when_an_agent_replied(self):
        client = _login_client(AGENT_USERNAME)
        response = client.get("/api/tickets/", {"is_overdue": "true"})
        self.assertEqual(response.status_code, 200)
        replied = {ticket.id for ticket in Ticket.objects.filter(first_response_at__isnull=False)}
        overdue = {ticket["id"] for ticket in response.data["results"]}
        self.assertFalse(overdue & replied)
        self.assertGreaterEqual(timedelta(0), timedelta(0))


class DemoGuardTests(TestCase):
    def test_seeding_is_refused_without_debug_or_force(self):
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            call_command("seed_demo")
        self.assertFalse(
            User.objects.filter(username__in=(CUSTOMER_USERNAME, AGENT_USERNAME)).exists()
        )

    def test_resetting_is_refused_without_debug_or_force(self):
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            call_command("reset_demo")
        self.assertFalse(Ticket.all_objects.exists())

    def test_debug_allows_seeding_without_force(self):
        with override_settings(DEBUG=True):
            call_command("seed_demo", stdout=StringIO())
        self.assertTrue(User.objects.filter(username=AGENT_USERNAME).exists())

    def test_force_allows_seeding_when_debug_is_off(self):
        with override_settings(DEBUG=False):
            call_command("seed_demo", force=True, stdout=StringIO())
        self.assertTrue(User.objects.filter(username=AGENT_USERNAME).exists())
