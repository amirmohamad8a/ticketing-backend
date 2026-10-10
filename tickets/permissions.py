from rest_framework.permissions import BasePermission

from accounts.models import User
from tickets.models import Ticket

STAFF_ONLY_FIELDS = frozenset({"status", "priority", "assignee"})


def _is_customer(user):
    return getattr(user, "role", None) == User.Role.CUSTOMER


def _is_admin(user):
    return getattr(user, "role", None) == User.Role.ADMIN


def _staff_only_fields_in(data):
    if not hasattr(data, "keys"):
        return set()
    return STAFF_ONLY_FIELDS.intersection(data.keys())


class IsAgentOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in (User.Role.AGENT, User.Role.ADMIN)
        )


class IsCustomerOwnerOrReadOwn(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.user.role in (User.Role.AGENT, User.Role.ADMIN):
            return True
        return obj.customer_id == request.user.id


class CustomerFieldRestrictions(BasePermission):
    def has_permission(self, request, view):
        if not _is_customer(request.user):
            return True
        if getattr(view, "action", None) != "create":
            return True
        return self._allows_fields(request)

    def has_object_permission(self, request, view, obj):
        if not _is_customer(request.user):
            return True
        if request.method not in ("PUT", "PATCH"):
            return True
        if not self._allows_fields(request):
            return False
        if obj.status != Ticket.Status.OPEN:
            self.message = "Customers can only edit a ticket while it is open."
            return False
        return True

    def _allows_fields(self, request):
        forbidden = _staff_only_fields_in(request.data)
        if forbidden:
            self.message = f"Customers cannot set: {', '.join(sorted(forbidden))}."
            return False
        return True


class AdminOnlyDeleteAndRestore(BasePermission):
    message = "Only admins can delete or restore tickets."

    def has_permission(self, request, view):
        if getattr(view, "action", None) == "restore":
            return _is_admin(request.user)
        return True

    def has_object_permission(self, request, view, obj):
        if getattr(view, "action", None) == "destroy":
            return _is_admin(request.user)
        return True
