from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404

import pytest
from rest_framework import exceptions
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from core.exceptions import custom_exception_handler
from tickets.models import Ticket

ENVELOPE_KEYS = {"code", "message", "details"}


def _assert_envelope(data, code):
    assert set(data.keys()) == {"error"}
    assert set(data["error"].keys()) == ENVELOPE_KEYS
    assert data["error"]["code"] == code


def _client_for(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


@pytest.mark.parametrize(
    "exc,status_code,code",
    [
        (exceptions.PermissionDenied(), 403, "permission_denied"),
        (DjangoPermissionDenied(), 403, "permission_denied"),
        (exceptions.NotAuthenticated(), 401, "not_authenticated"),
        (exceptions.MethodNotAllowed("PUT"), 405, "method_not_allowed"),
        (exceptions.NotFound(), 404, "not_found"),
        (Http404(), 404, "not_found"),
    ],
)
def test_handler_wraps_non_validation_errors(exc, status_code, code):
    response = custom_exception_handler(exc, {})
    assert response.status_code == status_code
    _assert_envelope(response.data, code)
    assert response.data["error"]["details"] is None


def test_handler_keeps_field_errors_under_details():
    exc = exceptions.ValidationError({"title": ["This field is required."]})
    response = custom_exception_handler(exc, {})
    assert response.status_code == 400
    _assert_envelope(response.data, "validation_error")
    assert response.data["error"]["details"] == {"title": ["This field is required."]}


def test_handler_ignores_unhandled_exceptions():
    assert custom_exception_handler(ValueError("boom"), {}) is None


@pytest.mark.django_db
def test_unauthenticated_request_returns_envelope():
    response = APIClient().get("/api/tickets/")
    assert response.status_code == 401
    _assert_envelope(response.data, "not_authenticated")


@pytest.mark.django_db
def test_other_customers_ticket_returns_envelope_404():
    owner = User.objects.create_user(username="ex_owner", password="pass12345")
    other = User.objects.create_user(username="ex_other", password="pass12345")
    ticket = Ticket.objects.create(title="t", description="d", customer=owner)
    response = _client_for(other).get(f"/api/tickets/{ticket.id}/")
    assert response.status_code == 404
    _assert_envelope(response.data, "not_found")


@pytest.mark.django_db
def test_invalid_ticket_payload_returns_validation_envelope():
    user = User.objects.create_user(username="ex_user", password="pass12345")
    response = _client_for(user).post("/api/tickets/", {"description": "d"})
    assert response.status_code == 400
    _assert_envelope(response.data, "validation_error")
    assert "title" in response.data["error"]["details"]


@pytest.mark.django_db
def test_logout_without_refresh_token_returns_validation_envelope():
    user = User.objects.create_user(username="ex_logout", password="pass12345")
    response = _client_for(user).post("/api/auth/logout/", {})
    assert response.status_code == 400
    _assert_envelope(response.data, "validation_error")
    assert "refresh" in response.data["error"]["details"]
