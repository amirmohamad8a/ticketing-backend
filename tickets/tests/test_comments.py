from django.test import TestCase

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from tickets.models import Comment, Ticket
from tickets.validators import MAX_BODY_LENGTH


def _auth(client, user):
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


class CommentVisibilityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create_user(
            username="cv_cust", password="pass12345", role=User.Role.CUSTOMER
        )
        self.other_customer = User.objects.create_user(
            username="cv_cust2", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="cv_agent", password="pass12345", role=User.Role.AGENT
        )
        self.admin = User.objects.create_user(
            username="cv_admin", password="pass12345", role=User.Role.ADMIN
        )
        self.ticket = Ticket.objects.create(title="t", description="d", customer=self.customer)
        self.public_comment = Comment.objects.create(
            ticket=self.ticket, author=self.customer, body="Any update?", is_internal=False
        )
        self.internal_comment = Comment.objects.create(
            ticket=self.ticket, author=self.agent, body="Escalating to backend.", is_internal=True
        )

    def _auth(self, user):
        _auth(self.client, user)

    def test_unauthenticated_list_rejected(self):
        response = self.client.get(f"/api/tickets/{self.ticket.id}/comments/")
        self.assertEqual(response.status_code, 401)

    def test_customer_never_receives_internal_comments(self):
        self._auth(self.customer)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/comments/")
        self.assertEqual(response.status_code, 200)
        ids = [c["id"] for c in response.data]
        self.assertNotIn(self.internal_comment.id, ids)
        self.assertIn(self.public_comment.id, ids)
        bodies = [c["body"] for c in response.data]
        self.assertNotIn(self.internal_comment.body, bodies)

    def test_agent_receives_internal_and_public_comments(self):
        self._auth(self.agent)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/comments/")
        self.assertEqual(response.status_code, 200)
        ids = {c["id"] for c in response.data}
        self.assertEqual(ids, {self.public_comment.id, self.internal_comment.id})

    def test_admin_receives_internal_and_public_comments(self):
        self._auth(self.admin)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/comments/")
        self.assertEqual(response.status_code, 200)
        ids = {c["id"] for c in response.data}
        self.assertEqual(ids, {self.public_comment.id, self.internal_comment.id})

    def test_other_customer_cannot_list_comments(self):
        self._auth(self.other_customer)
        response = self.client.get(f"/api/tickets/{self.ticket.id}/comments/")
        self.assertEqual(response.status_code, 404)


class CommentCreationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create_user(
            username="cc_cust", password="pass12345", role=User.Role.CUSTOMER
        )
        self.other_customer = User.objects.create_user(
            username="cc_cust2", password="pass12345", role=User.Role.CUSTOMER
        )
        self.agent = User.objects.create_user(
            username="cc_agent", password="pass12345", role=User.Role.AGENT
        )
        self.ticket = Ticket.objects.create(title="t", description="d", customer=self.customer)

    def _auth(self, user):
        _auth(self.client, user)

    def test_unauthenticated_create_rejected(self):
        response = self.client.post(f"/api/tickets/{self.ticket.id}/comments/", {"body": "hi"})
        self.assertEqual(response.status_code, 401)

    def test_customer_can_create_public_comment(self):
        self._auth(self.customer)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/comments/", {"body": "Any update?"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["is_internal"])
        self.assertEqual(response.data["author"], self.customer.id)
        self.assertEqual(response.data["ticket"], self.ticket.id)

    def test_customer_cannot_force_internal_flag(self):
        self._auth(self.customer)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/comments/",
            {"body": "Trying to sneak this in", "is_internal": True},
        )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["is_internal"])
        comment = Comment.objects.get(id=response.data["id"])
        self.assertFalse(comment.is_internal)

    def test_agent_can_create_internal_comment(self):
        self._auth(self.agent)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/comments/",
            {"body": "Escalating to backend.", "is_internal": True},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["is_internal"])
        self.assertEqual(response.data["author"], self.agent.id)

    def test_agent_can_create_public_comment(self):
        self._auth(self.agent)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/comments/", {"body": "Looking into it."}
        )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["is_internal"])

    def test_other_customer_cannot_create_comment_on_ticket(self):
        self._auth(self.other_customer)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/comments/", {"body": "Not my ticket"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Comment.objects.filter(ticket=self.ticket, body="Not my ticket").exists())

    def test_missing_body_rejected(self):
        self._auth(self.customer)
        response = self.client.post(f"/api/tickets/{self.ticket.id}/comments/", {})
        self.assertEqual(response.status_code, 400)

    def test_oversized_body_is_rejected(self):
        self._auth(self.customer)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/comments/",
            {"body": "x" * (MAX_BODY_LENGTH + 1)},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "validation_error")
        self.assertIn("body", response.data["error"]["details"])
        self.assertFalse(Comment.objects.filter(ticket=self.ticket, body__startswith="x").exists())

    def test_a_body_at_the_limit_is_accepted(self):
        self._auth(self.customer)
        response = self.client.post(
            f"/api/tickets/{self.ticket.id}/comments/",
            {"body": "x" * MAX_BODY_LENGTH},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data["body"]), MAX_BODY_LENGTH)
