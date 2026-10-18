from django.db import connection
from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.search import ARABIC_KAF, ARABIC_YEH, MAX_SEARCH_LENGTH, PERSIAN_KAF, PERSIAN_YEH
from core.tests.factories import (
    AdminFactory,
    AgentFactory,
    CommentFactory,
    TicketFactory,
    UserFactory,
)
from tickets.models import Comment, Ticket
from tickets.search import search_tickets

URL = "/api/tickets/"
ZWNJ = "\u200c"
PERSIAN_YEH_WORD = "\u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc"
ARABIC_YEH_WORD = PERSIAN_YEH_WORD.replace(PERSIAN_YEH, ARABIC_YEH)
PERSIAN_KAF_WORD = f"{PERSIAN_KAF}\u062a\u0627\u0628"
ARABIC_KAF_WORD = PERSIAN_KAF_WORD.replace(PERSIAN_KAF, ARABIC_KAF)
JOINED_PHRASE = f"\u0645\u06cc{ZWNJ}\u062e\u0648\u0627\u0647\u0645"
SPACED_PHRASE = "\u0645\u06cc \u062e\u0648\u0627\u0647\u0645"


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _ids(response):
    return {ticket["id"] for ticket in response.data["results"]}


class TicketSearchTests(TestCase):
    def setUp(self):
        self.customer = UserFactory()
        self.agent = AgentFactory()
        self.staff = _client_for(self.agent)
        self.owner = _client_for(self.customer)

    def _ticket(self, title="Plain title", description="Plain description", **kwargs):
        kwargs.setdefault("customer", self.customer)
        return TicketFactory(title=title, description=description, **kwargs)

    def _search(self, client, term, **params):
        response = client.get(URL, {"search": term, **params})
        self.assertEqual(response.status_code, 200)
        return _ids(response)

    def test_titles_are_searched(self):
        printer = self._ticket(title="Printer on fire")
        self._ticket(title="Keyboard broken")
        self.assertEqual(self._search(self.staff, "printer"), {printer.id})

    def test_descriptions_are_searched(self):
        wanted = self._ticket(description="The scanner makes a loud noise")
        self._ticket(description="Nothing special")
        self.assertEqual(self._search(self.staff, "scanner"), {wanted.id})

    def test_public_messages_are_searched(self):
        ticket = self._ticket()
        CommentFactory(ticket=ticket, author=self.agent, body="Replacement shipped yesterday")
        self._ticket()
        self.assertEqual(self._search(self.staff, "replacement"), {ticket.id})

    def test_matching_ignores_case(self):
        ticket = self._ticket(title="Printer on fire")
        self.assertEqual(self._search(self.staff, "PRINTER"), {ticket.id})

    def test_only_whole_words_match(self):
        self._ticket(title="Printer on fire")
        self.assertEqual(self._search(self.staff, "print"), set())

    def test_every_word_of_the_term_must_match(self):
        wanted = self._ticket(title="Login error on mobile")
        self._ticket(title="Login page is slow")
        self.assertEqual(self._search(self.staff, "login error"), {wanted.id})

    def test_a_minus_sign_excludes_a_word(self):
        wanted = self._ticket(title="Printer jammed")
        self._ticket(title="Printer on fire")
        self.assertEqual(self._search(self.staff, "printer -fire"), {wanted.id})

    def test_a_quoted_phrase_must_match_in_order(self):
        wanted = self._ticket(title="Printer on fire")
        self._ticket(title="Fire on printer")
        self.assertEqual(self._search(self.staff, '"on fire"'), {wanted.id})

    def test_a_ticket_matching_in_several_places_is_listed_once(self):
        ticket = self._ticket(title="Refund request", description="Refund please")
        CommentFactory(ticket=ticket, author=self.agent, body="Refund approved")
        response = self.staff.get(URL, {"search": "refund"})
        self.assertEqual([row["id"] for row in response.data["results"]], [ticket.id])

    def test_staff_find_internal_notes_but_customers_never_do(self):
        ticket = self._ticket(title="Hidden")
        CommentFactory(
            ticket=ticket, author=self.agent, body="escalated to billing", is_internal=True
        )
        self.assertEqual(self._search(self.staff, "escalated"), {ticket.id})
        self.assertEqual(self._search(_client_for(AdminFactory()), "escalated"), {ticket.id})
        self.assertEqual(self._search(self.owner, "escalated"), set())

    def test_customers_find_public_staff_replies(self):
        ticket = self._ticket()
        CommentFactory(ticket=ticket, author=self.agent, body="Please restart the router")
        self.assertEqual(self._search(self.owner, "router"), {ticket.id})

    def test_customers_only_search_their_own_tickets(self):
        mine = self._ticket(title="Invoice mismatch")
        self._ticket(title="Invoice mismatch", customer=UserFactory())
        self.assertEqual(self._search(self.owner, "invoice"), {mine.id})

    def test_system_messages_are_not_searched(self):
        ticket = self._ticket()
        CommentFactory(
            ticket=ticket,
            author=None,
            visitor=None,
            kind=Comment.Kind.SYSTEM,
            body="uniquesystemword",
        )
        self.assertEqual(self._search(self.staff, "uniquesystemword"), set())

    def test_visitor_messages_are_searched_by_staff(self):
        ticket = TicketFactory(from_visitor=True)
        CommentFactory(
            ticket=ticket, author=None, visitor=ticket.visitor, body="where is my parcel"
        )
        self.assertEqual(self._search(self.staff, "parcel"), {ticket.id})
        self.assertEqual(self._search(self.owner, "parcel"), set())

    def test_deleted_tickets_are_not_found(self):
        ticket = self._ticket(title="Ghost ticket")
        ticket.delete()
        self.assertEqual(self._search(self.staff, "ghost"), set())

    def test_either_yeh_spelling_finds_either_stored_spelling(self):
        persian = self._ticket(title=f"{PERSIAN_YEH_WORD} one")
        arabic = self._ticket(title=f"{ARABIC_YEH_WORD} two")
        for term in (PERSIAN_YEH_WORD, ARABIC_YEH_WORD):
            with self.subTest(term=term):
                self.assertEqual(self._search(self.staff, term), {persian.id, arabic.id})

    def test_either_kaf_spelling_finds_either_stored_spelling(self):
        persian = self._ticket(description=f"{PERSIAN_KAF_WORD} one")
        arabic = self._ticket(description=f"{ARABIC_KAF_WORD} two")
        for term in (PERSIAN_KAF_WORD, ARABIC_KAF_WORD):
            with self.subTest(term=term):
                self.assertEqual(self._search(self.staff, term), {persian.id, arabic.id})

    def test_variant_spellings_are_found_in_messages_too(self):
        ticket = self._ticket()
        CommentFactory(ticket=ticket, author=self.agent, body=f"{ARABIC_YEH_WORD} done")
        self.assertEqual(self._search(self.staff, PERSIAN_YEH_WORD), {ticket.id})

    def test_ascii_and_persian_digits_find_each_other(self):
        ascii_ticket = self._ticket(title="\u0633\u0641\u0627\u0631\u0634 12480")
        persian_ticket = self._ticket(
            title="\u0633\u0641\u0627\u0631\u0634 \u06f1\u06f2\u06f4\u06f8\u06f0"
        )
        for term in ("12480", "\u06f1\u06f2\u06f4\u06f8\u06f0", "\u0661\u0662\u0664\u0668\u0660"):
            with self.subTest(term=term):
                self.assertEqual(
                    self._search(self.staff, term), {ascii_ticket.id, persian_ticket.id}
                )

    def test_a_zero_width_non_joiner_and_a_space_are_the_same(self):
        joined = self._ticket(title=f"{JOINED_PHRASE} cancel")
        spaced = self._ticket(title=f"{SPACED_PHRASE} change")
        for term in (JOINED_PHRASE, SPACED_PHRASE):
            with self.subTest(term=term):
                self.assertEqual(self._search(self.staff, term), {joined.id, spaced.id})

    def test_a_term_that_normalizes_to_nothing_matches_nothing(self):
        self._ticket()
        self.assertEqual(self._search(self.staff, ZWNJ), set())

    def test_overlong_terms_are_rejected(self):
        response = self.staff.get(URL, {"search": "a" * (MAX_SEARCH_LENGTH + 1)})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("search", response.data["error"]["details"])

    def test_a_term_at_the_limit_is_accepted(self):
        self.assertEqual(self._search(self.staff, "a" * MAX_SEARCH_LENGTH), set())

    def test_search_combines_with_other_filters(self):
        open_ticket = self._ticket(title="Printer one", status=Ticket.Status.OPEN)
        self._ticket(title="Printer two", status=Ticket.Status.IN_PROGRESS)
        self.assertEqual(self._search(self.staff, "printer", status="open"), {open_ticket.id})

    def test_the_term_survives_pagination(self):
        for index in range(25):
            self._ticket(title=f"bulk item {index}")
        self._ticket(title="something else")
        seen = []
        response = self.staff.get(URL, {"search": "bulk"})
        while True:
            self.assertEqual(response.status_code, 200)
            seen.extend(row["id"] for row in response.data["results"])
            if not response.data["next"]:
                break
            response = self.staff.get(response.data["next"])
        self.assertEqual(len(seen), 25)
        self.assertEqual(len(set(seen)), 25)

    def test_the_service_returns_nothing_for_an_empty_term(self):
        self._ticket()
        for term in ("", "   ", ZWNJ):
            with self.subTest(term=term):
                self.assertEqual(search_tickets(Ticket.objects.all(), term, True).count(), 0)


class SearchIndexTests(TestCase):
    def _definition(self, name):
        with connection.cursor() as cursor:
            cursor.execute("SELECT indexdef FROM pg_indexes WHERE indexname = %s", [name])
            row = cursor.fetchone()
        return row[0] if row else ""

    def test_the_ticket_search_index_is_a_gin_index(self):
        self.assertIn("USING gin", self._definition("ticket_search_gin"))

    def test_the_comment_search_index_is_a_gin_index(self):
        self.assertIn("USING gin", self._definition("comment_search_gin"))
