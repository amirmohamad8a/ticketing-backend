import shutil
import tempfile

from django.test import TestCase, override_settings

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from chat.tokens import issue_visitor_token
from core.tests.factories import (
    AgentFactory,
    AttachmentFactory,
    CommentFactory,
    SiteFactory,
    TicketFactory,
    UserFactory,
    VisitorFactory,
)
from tickets.models import Attachment

TEST_MEDIA_ROOT = tempfile.mkdtemp()


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class PortalDownloadVisibilityParityTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.customer = UserFactory()
        self.other_customer = UserFactory()
        self.agent = AgentFactory()
        self.ticket = TicketFactory(customer=self.customer)
        self.public_comment = CommentFactory(ticket=self.ticket, author=self.customer)
        self.internal_comment = CommentFactory(
            ticket=self.ticket, author=self.agent, is_internal=True
        )
        self.ticket_attachment = AttachmentFactory(ticket=self.ticket, uploaded_by=self.customer)
        self.public_attachment = AttachmentFactory(
            on_comment=True, comment=self.public_comment, uploaded_by=self.customer
        )
        self.internal_attachment = AttachmentFactory(
            on_comment=True, comment=self.internal_comment, uploaded_by=self.agent
        )

    def _visible_attachment_ids(self, user):
        client = _client_for(user)
        visible = set()

        ticket_response = client.get(f"/api/tickets/{self.ticket.id}/attachments/")
        if ticket_response.status_code == 200:
            visible.update(row["id"] for row in ticket_response.data)

        comments_response = client.get(f"/api/tickets/{self.ticket.id}/comments/")
        if comments_response.status_code == 200:
            for comment in comments_response.data:
                response = client.get(
                    f"/api/tickets/{self.ticket.id}/comments/{comment['id']}/attachments/"
                )
                if response.status_code == 200:
                    visible.update(row["id"] for row in response.data)
        return visible

    def test_download_visibility_matches_the_portal_list_views_for_every_participant(self):
        expected = {
            self.customer: {self.ticket_attachment.id, self.public_attachment.id},
            self.agent: {
                self.ticket_attachment.id,
                self.public_attachment.id,
                self.internal_attachment.id,
            },
            self.other_customer: set(),
        }
        for user, visible in expected.items():
            with self.subTest(role=user.role, username=user.username):
                self.assertEqual(self._visible_attachment_ids(user), visible)
                client = _client_for(user)
                for attachment in Attachment.objects.all():
                    response = client.get(f"/api/attachments/{attachment.id}/download/")
                    if attachment.id in visible:
                        self.assertEqual(response.status_code, 200)
                    else:
                        self.assertEqual(response.status_code, 404)

    def test_internal_attachments_are_invisible_through_both_portal_paths(self):
        self.assertNotIn(self.internal_attachment.id, self._visible_attachment_ids(self.customer))
        response = _client_for(self.customer).get(
            f"/api/attachments/{self.internal_attachment.id}/download/"
        )
        self.assertEqual(response.status_code, 404)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class WidgetDownloadVisibilityParityTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.site = SiteFactory(allowed_origins=["https://example.com"])
        self.agent = AgentFactory()
        self.visitor = VisitorFactory(site=self.site)
        self.other_visitor = VisitorFactory(site=self.site)
        self.ticket = TicketFactory(from_visitor=True, visitor=self.visitor)
        self.other_ticket = TicketFactory(from_visitor=True, visitor=self.other_visitor)

        self.public_comment = CommentFactory(ticket=self.ticket, author=self.agent)
        self.internal_comment = CommentFactory(
            ticket=self.ticket, author=self.agent, is_internal=True
        )
        self.public_attachment = AttachmentFactory(
            on_comment=True, comment=self.public_comment, uploaded_by=self.agent
        )
        self.internal_attachment = AttachmentFactory(
            on_comment=True, comment=self.internal_comment, uploaded_by=self.agent
        )
        self.ticket_attachment = AttachmentFactory(ticket=self.ticket, uploaded_by=self.agent)
        other_comment = CommentFactory(ticket=self.other_ticket, author=self.agent)
        self.other_attachment = AttachmentFactory(
            on_comment=True, comment=other_comment, uploaded_by=self.agent
        )

        self.client = APIClient()
        self.client.credentials(
            HTTP_X_VISITOR_TOKEN=issue_visitor_token(self.visitor),
            HTTP_ORIGIN="https://example.com",
        )

    def _visible_attachment_ids(self):
        response = self.client.get(f"/api/widget/conversations/{self.ticket.id}/messages/")
        self.assertEqual(response.status_code, 200)
        visible = set()
        for message in response.data["results"]:
            visible.update(attachment["id"] for attachment in message["attachments"])
        return visible

    def test_download_visibility_matches_the_widget_message_list(self):
        visible = self._visible_attachment_ids()
        self.assertEqual(visible, {self.public_attachment.id})

        for attachment in Attachment.objects.all():
            response = self.client.get(f"/api/widget/attachments/{attachment.id}/download/")
            if attachment.id in visible:
                self.assertEqual(response.status_code, 200)
            else:
                self.assertEqual(response.status_code, 404)

    def test_internal_notes_and_other_visitors_never_leak_attachments(self):
        visible = self._visible_attachment_ids()
        for hidden in (
            self.internal_attachment,
            self.ticket_attachment,
            self.other_attachment,
        ):
            with self.subTest(attachment=hidden.id):
                self.assertNotIn(hidden.id, visible)
                response = self.client.get(f"/api/widget/attachments/{hidden.id}/download/")
                self.assertEqual(response.status_code, 404)
