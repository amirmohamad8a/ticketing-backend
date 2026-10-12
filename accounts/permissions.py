from rest_framework.permissions import BasePermission

from accounts.models import User

STAFF_ROLES = (User.Role.AGENT, User.Role.ADMIN)


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and request.user.role == User.Role.ADMIN
        )


def can_view_avatar(viewer, owner):
    return viewer.pk == owner.pk or viewer.role in STAFF_ROLES or owner.role in STAFF_ROLES
