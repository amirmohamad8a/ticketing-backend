import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from tickets.models import Ticket

MATRIX = [
    ("unauthenticated", "list", 401),
    ("unauthenticated", "retrieve", 401),
    ("unauthenticated", "create", 401),
    ("unauthenticated", "update", 401),
    ("unauthenticated", "delete", 401),
    ("customer_owner", "list", 200),
    ("customer_owner", "retrieve", 200),
    ("customer_owner", "create", 201),
    ("customer_owner", "update", 200),
    ("customer_owner", "delete", 204),
    ("customer_other", "list", 200),
    ("customer_other", "retrieve", 404),
    ("customer_other", "create", 201),
    ("customer_other", "update", 404),
    ("customer_other", "delete", 404),
    ("agent", "list", 200),
    ("agent", "retrieve", 200),
    ("agent", "create", 201),
    ("agent", "update", 200),
    ("agent", "delete", 204),
    ("admin", "list", 200),
    ("admin", "retrieve", 200),
    ("admin", "create", 201),
    ("admin", "update", 200),
    ("admin", "delete", 204),
]


@pytest.mark.django_db
@pytest.mark.parametrize("role,action,expected_status", MATRIX)
def test_ticket_permission_matrix(role, action, expected_status):
    customer_owner = User.objects.create_user(
        username="pm_owner", password="pass12345", role=User.Role.CUSTOMER
    )
    customer_other = User.objects.create_user(
        username="pm_other", password="pass12345", role=User.Role.CUSTOMER
    )
    agent = User.objects.create_user(
        username="pm_agent", password="pass12345", role=User.Role.AGENT
    )
    admin = User.objects.create_user(
        username="pm_admin", password="pass12345", role=User.Role.ADMIN
    )
    ticket = Ticket.objects.create(title="Matrix ticket", description="d", customer=customer_owner)

    client = APIClient()
    user_map = {
        "customer_owner": customer_owner,
        "customer_other": customer_other,
        "agent": agent,
        "admin": admin,
    }
    if role != "unauthenticated":
        user = user_map[role]
        refresh = RefreshToken.for_user(user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    if action == "list":
        response = client.get("/api/tickets/")
    elif action == "retrieve":
        response = client.get(f"/api/tickets/{ticket.id}/")
    elif action == "create":
        response = client.post("/api/tickets/", {"title": "New ticket", "description": "d"})
    elif action == "update":
        response = client.patch(f"/api/tickets/{ticket.id}/", {"title": "Updated title"})
    elif action == "delete":
        response = client.delete(f"/api/tickets/{ticket.id}/")

    assert response.status_code == expected_status
