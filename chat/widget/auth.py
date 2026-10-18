from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import BasePermission

from chat.models import Visitor
from chat.tokens import InvalidVisitorToken
from chat.validators import normalize_origin
from chat.visitors import resolve_visitor

TOKEN_META_KEY = "HTTP_X_VISITOR_TOKEN"
ORIGIN_META_KEY = "HTTP_ORIGIN"


class VisitorTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        token = request.META.get(TOKEN_META_KEY, "")
        if not token:
            return None
        try:
            visitor = resolve_visitor(token)
        except InvalidVisitorToken:
            raise AuthenticationFailed(_("The visitor token is invalid or has expired."))
        return AnonymousUser(), visitor

    def authenticate_header(self, request):
        return "Visitor"


def origin_allowed_for_site(origin, site):
    if not origin:
        return False
    try:
        normalized = normalize_origin(origin)
    except DjangoValidationError:
        return False
    return normalized in site.allowed_origins


def is_origin_allowed(request, site):
    return origin_allowed_for_site(request.META.get(ORIGIN_META_KEY, ""), site)


def ensure_origin_allowed(request, site):
    if not is_origin_allowed(request, site):
        raise PermissionDenied(_("This origin is not allowed for the site."))


class IsVisitorFromAllowedOrigin(BasePermission):
    message = _("This origin is not allowed for the site.")

    def has_permission(self, request, view):
        visitor = request.auth
        if not isinstance(visitor, Visitor):
            return False
        return is_origin_allowed(request, visitor.site)
