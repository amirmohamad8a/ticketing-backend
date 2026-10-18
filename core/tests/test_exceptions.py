import json

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from django.test import override_settings
from django.urls import path

import pytest
from rest_framework import exceptions
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from config.urls import handler400, handler404, handler500
from core.exceptions import custom_exception_handler
from tickets.models import Ticket

ENVELOPE_KEYS = {"code", "message", "details"}


def _boom(request):
    raise RuntimeError("boom")


urlpatterns = [path("boom/", _boom)]


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


def _envelope(response):
    return json.loads(response.content)


@pytest.mark.parametrize(
    "handler,status_code,code",
    [
        (lambda: handler400(None), 400, "bad_request"),
        (lambda: handler404(None, Http404()), 404, "not_found"),
        (lambda: handler500(None), 500, "server_error"),
    ],
)
def test_django_error_handlers_return_the_envelope(handler, status_code, code):
    response = handler()
    assert response.status_code == status_code
    assert response["Content-Type"] == "application/json"
    _assert_envelope(_envelope(response), code)


@pytest.mark.django_db
@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
def test_unknown_route_returns_a_json_404_envelope():
    response = APIClient().get("/api/this-route-does-not-exist/")
    assert response.status_code == 404
    _assert_envelope(_envelope(response), "not_found")


@pytest.mark.django_db
@override_settings(DEBUG=False, ALLOWED_HOSTS=["support.example.com"])
def test_a_disallowed_host_returns_a_json_400_envelope():
    response = APIClient().get("/health/")
    assert response.status_code == 400
    _assert_envelope(_envelope(response), "bad_request")


@pytest.mark.django_db
@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"], ROOT_URLCONF=__name__)
def test_an_unhandled_error_returns_a_json_500_envelope():
    client = APIClient()
    client.raise_request_exception = False
    response = client.get("/boom/")
    assert response.status_code == 500
    _assert_envelope(_envelope(response), "server_error")
