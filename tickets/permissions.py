from rest_framework.permissions import BasePermission

from accounts.models import User


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
