from django.core.files.base import ContentFile
from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.tests.factories import (
    AdminFactory,
    AgentFactory,
    AttachmentFactory,
    CommentFactory,
    TicketFactory,
    UserFactory,
)
from core.tests.security_support import (
    ORIGIN,
    client_for,
    make_world,
    upload,
    use_temp_media,
    visitor_client,
)
from tickets.models import Attachment, Comment, Ticket


class TicketRouteIdorTests(TestCase):
    def setUp(self):
        use_temp_media(self)
        self.owner = UserFactory()
        self.intruder = UserFactory()
        self.agent = AgentFactory()
        self.admin = AdminFactory()
        self.ticket = TicketFactory(customer=self.owner)
        self.comment = CommentFactory(ticket=self.ticket, author=self.owner)
        self.internal = CommentFactory(ticket=self.ticket, author=self.agent, is_internal=True)
        AttachmentFactory(ticket=self.ticket, uploaded_by=self.owner)
        AttachmentFactory(on_comment=True, comment=self.comment, uploaded_by=self.owner)
        AttachmentFactory(on_comment=True, comment=self.internal, uploaded_by=self.agent)
        self.intruder_client = client_for(self.intruder)

    def _routes(self, ticket_id):
        base = f"/api/tickets/{ticket_id}/"
        return [
            base,
            f"{base}comments/",
            f"{base}attachments/",
            f"{base}events/",
            f"{base}messages/",
            f"{base}rating/",
            f"{base}comments/{self.comment.id}/attachments/",
            f"{base}comments/{self.internal.id}/attachments/",
        ]

    def test_an_intruder_cannot_read_any_route_of_the_ticket(self):
        for url in self._routes(self.ticket.id):
            with self.subTest(url=url):
                response = self.intruder_client.get(url)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.data["error"]["code"], "not_found")

    def test_an_intruder_cannot_tell_a_foreign_ticket_from_a_missing_one(self):
        for real, missing in zip(self._routes(self.ticket.id), self._routes(999999), strict=True):
            with self.subTest(url=real):
                first = self.intruder_client.get(real)
                second = self.intruder_client.get(missing)
                self.assertEqual(first.status_code, second.status_code)
                self.assertEqual(first.data, second.data)

    def test_an_intruder_cannot_write_through_any_route(self):
        client = self.intruder_client
        base = f"/api/tickets/{self.ticket.id}/"
        comments_before = Comment.objects.count()
        attachments_before = Attachment.objects.count()
        responses = [
            client.post(f"{base}comments/", {"body": "intruder"}, format="json"),
            client.post(f"{base}attachments/", {"file": upload(b"hello")}),
            client.post(
                f"{base}comments/{self.comment.id}/attachments/", {"file": upload(b"hello")}
            ),
            client.post(f"{base}read/", {}, format="json"),
            client.post(f"{base}rating/", {"score": 5}, format="json"),
            client.patch(base, {"title": "hijacked"}, format="json"),
            client.put(base, {"title": "hijacked", "description": "d"}, format="json"),
            client.delete(base),
        ]
        for response in responses:
            self.assertEqual(response.status_code, 404)
        for suffix in ("claim/", "restore/"):
            with self.subTest(suffix=suffix):
                self.assertEqual(client.post(f"{base}{suffix}").status_code, 403)
        self.assertEqual(Comment.objects.count(), comments_before)
        self.assertEqual(Attachment.objects.count(), attachments_before)
        self.ticket.refresh_from_db()
        self.assertNotEqual(self.ticket.title, "hijacked")
        self.assertFalse(self.ticket.is_deleted)

    def test_a_comment_of_another_ticket_is_unreachable_through_this_ticket(self):
        other_ticket = TicketFactory(customer=self.owner)
        other_comment = CommentFactory(ticket=other_ticket, author=self.owner)
        url = f"/api/tickets/{self.ticket.id}/comments/{other_comment.id}/attachments/"
        for user in (self.owner, self.agent, self.admin):
            with self.subTest(role=user.role):
                self.assertEqual(client_for(user).get(url).status_code, 404)
        before = Attachment.objects.count()
        response = client_for(self.owner).post(url, {"file": upload(b"hello")})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Attachment.objects.count(), before)

    def test_a_read_marker_cannot_point_at_a_message_of_another_ticket(self):
        other_ticket = TicketFactory(customer=self.owner)
        other_comment = CommentFactory(ticket=other_ticket, author=self.owner)
        url = f"/api/tickets/{self.ticket.id}/read/"
        client = client_for(self.owner)
        for comment_id in (other_comment.id, self.internal.id, 999999):
            with self.subTest(comment_id=comment_id):
                response = client.post(url, {"last_read_comment_id": comment_id}, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertIn("last_read_comment_id", response.data["error"]["details"])

    def test_a_deleted_ticket_disappears_from_every_route_for_everyone(self):
        self.ticket.delete()
        for user in (self.owner, self.agent, self.admin):
            client = client_for(user)
            for url in self._routes(self.ticket.id):
                with self.subTest(role=user.role, url=url):
                    self.assertEqual(client.get(url).status_code, 404)
            read = client.post(f"/api/tickets/{self.ticket.id}/read/", {}, format="json")
            self.assertEqual(read.status_code, 404)
        claim = client_for(self.agent).post(f"/api/tickets/{self.ticket.id}/claim/")
        self.assertEqual(claim.status_code, 404)

    def test_the_owner_cannot_be_changed_through_a_payload(self):
        response = client_for(self.owner).patch(
            f"/api/tickets/{self.ticket.id}/",
            {"title": "renamed", "customer": self.intruder.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.customer, self.owner)
        self.assertEqual(self.ticket.title, "renamed")


class DownloadIdorTests(TestCase):
    def setUp(self):
        use_temp_media(self)
        self.owner = UserFactory()
        self.intruder = UserFactory()
        self.agent = AgentFactory()
        self.ticket = TicketFactory(customer=self.owner)
        self.comment = CommentFactory(ticket=self.ticket, author=self.owner)
        self.internal = CommentFactory(ticket=self.ticket, author=self.agent, is_internal=True)
        self.files = [
            AttachmentFactory(ticket=self.ticket, uploaded_by=self.owner),
            AttachmentFactory(on_comment=True, comment=self.comment, uploaded_by=self.owner),
            AttachmentFactory(on_comment=True, comment=self.internal, uploaded_by=self.agent),
        ]

    def test_an_intruder_gets_no_link_and_cannot_tell_the_file_exists(self):
        client = client_for(self.intruder)
        missing = client.get("/api/attachments/999999/download/")
        for attachment in self.files:
            with self.subTest(attachment=attachment.id):
                response = client.get(f"/api/attachments/{attachment.id}/download/")
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.data, missing.data)

    def test_the_owner_never_gets_a_link_to_an_internal_attachment(self):
        response = client_for(self.owner).get(f"/api/attachments/{self.files[2].id}/download/")
        self.assertEqual(response.status_code, 404)

    def test_a_customer_never_gets_a_link_to_a_visitor_conversation_file(self):
        ticket = TicketFactory(from_visitor=True)
        comment = CommentFactory(ticket=ticket, author=None, visitor=ticket.visitor)
        attachment = AttachmentFactory(on_comment=True, comment=comment, uploaded_by=None)
        url = f"/api/attachments/{attachment.id}/download/"
        self.assertEqual(client_for(self.owner).get(url).status_code, 404)
        self.assertEqual(client_for(self.agent).get(url).status_code, 200)

    def test_avatar_lookups_do_not_reveal_who_has_an_avatar(self):
        self.owner.avatar.save("avatar.png", ContentFile(b"avatar"), save=True)
        without_avatar = UserFactory()
        client = client_for(self.intruder)
        responses = [
            client.get(f"/api/avatars/{self.owner.id}/download/"),
            client.get(f"/api/avatars/{without_avatar.id}/download/"),
            client.get("/api/avatars/999999/download/"),
        ]
        for response in responses:
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.data["error"]["code"], "not_found")


class WidgetIdorTests(TestCase):
    def setUp(self):
        use_temp_media(self)
        self.world = make_world(with_files=True)

    def test_another_visitor_is_refused_on_every_route(self):
        world = self.world
        client = visitor_client(world.visitor_b)
        base = f"/api/widget/conversations/{world.ticket_a.id}/"
        before = Comment.objects.count()
        responses = [
            client.get(f"{base}messages/"),
            client.post(f"{base}messages/", {"body": "intruder"}, format="json"),
            client.post(f"{base}read/", {}, format="json"),
            client.get(f"{base}rating/"),
            client.post(f"{base}rating/", {"score": 5}, format="json"),
            client.post(f"{base}attachments/", {"file": upload(b"hello")}),
            client.get(f"/api/widget/attachments/{world.file_a.id}/download/"),
            client.get(f"/api/widget/attachments/{world.note_file_a.id}/download/"),
        ]
        for response in responses:
            self.assertEqual(response.status_code, 404)
        self.assertEqual(Comment.objects.count(), before)

    def test_a_foreign_conversation_looks_like_a_missing_one(self):
        client = visitor_client(self.world.visitor_b)
        foreign = client.get(f"/api/widget/conversations/{self.world.ticket_a.id}/messages/")
        missing = client.get("/api/widget/conversations/999999/messages/")
        self.assertEqual(foreign.status_code, missing.status_code)
        self.assertEqual(foreign.data, missing.data)

    def test_a_visitor_of_another_site_is_refused(self):
        from core.tests.factories import SiteFactory, VisitorFactory

        other_site = SiteFactory(allowed_origins=[ORIGIN])
        stranger = VisitorFactory(site=other_site)
        client = visitor_client(stranger)
        url = f"/api/widget/conversations/{self.world.ticket_a.id}/messages/"
        self.assertEqual(client.get(url).status_code, 404)

    def test_a_deleted_conversation_is_gone_for_its_visitor(self):
        self.world.ticket_a.delete()
        client = visitor_client(self.world.visitor_a)
        base = f"/api/widget/conversations/{self.world.ticket_a.id}/"
        self.assertEqual(client.get(f"{base}messages/").status_code, 404)
        self.assertEqual(
            client.post(f"{base}messages/", {"body": "hi"}, format="json").status_code, 404
        )
        self.assertEqual(Ticket.all_objects.filter(pk=self.world.ticket_a.pk).count(), 1)

    def test_a_visitor_never_gets_a_link_to_an_internal_note_file(self):
        client = visitor_client(self.world.visitor_a)
        url = f"/api/widget/attachments/{self.world.note_file_a.id}/download/"
        self.assertEqual(client.get(url).status_code, 404)

    def test_a_staff_token_does_not_open_the_widget_api(self):
        client = APIClient()
        refresh = RefreshToken.for_user(self.world.agent)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}", HTTP_ORIGIN=ORIGIN)
        url = f"/api/widget/conversations/{self.world.ticket_a.id}/messages/"
        self.assertEqual(client.get(url).status_code, 401)

    def test_a_visitor_token_does_not_open_any_staff_route(self):
        client = visitor_client(self.world.visitor_a)
        for url in ("/api/tickets/", "/api/auth/me/", "/api/stats/", "/api/agents/"):
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 401)
