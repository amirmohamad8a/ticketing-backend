from django.contrib import admin
from django.contrib.admin.utils import unquote
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db import transaction
from django.http import HttpResponseRedirect

from accounts.events import record_user_event
from accounts.models import User, UserEvent
from accounts.tokens import blacklist_user_tokens
from realtime.events import close_user_sockets


def _flag(value):
    return "true" if value else "false"


class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        (None, {"fields": ("role", "phone", "avatar", "max_concurrent_chats")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + ((None, {"fields": ("role", "phone")}),)
    list_display = DjangoUserAdmin.list_display + ("role", "phone")
    list_filter = DjangoUserAdmin.list_filter + ("role",)
    search_fields = DjangoUserAdmin.search_fields + ("phone",)

    def save_model(self, request, obj, form, change):
        actor = request.user
        if not change:
            with transaction.atomic():
                super().save_model(request, obj, form, change)
                record_user_event(
                    user=obj,
                    actor=actor,
                    field_changed="created",
                    old_value="",
                    new_value=obj.role,
                )
            return

        previous = User.objects.only("role", "is_active").get(pk=obj.pk)
        events = []
        if previous.role != obj.role:
            events.append(("role", previous.role, obj.role))
        if previous.is_active != obj.is_active:
            events.append(("is_active", _flag(previous.is_active), _flag(obj.is_active)))
        deactivated = previous.is_active and not obj.is_active

        with transaction.atomic():
            super().save_model(request, obj, form, change)
            if deactivated:
                blacklist_user_tokens(obj)
            for field_changed, old_value, new_value in events:
                record_user_event(
                    user=obj,
                    actor=actor,
                    field_changed=field_changed,
                    old_value=old_value,
                    new_value=new_value,
                )
            if events:
                close_user_sockets(obj.pk)

    def user_change_password(self, request, id, form_url=""):
        with transaction.atomic():
            response = super().user_change_password(request, id, form_url)
            if request.method != "POST" or not isinstance(response, HttpResponseRedirect):
                return response
            user = self.get_object(request, unquote(id))
            if user is None:
                return response
            blacklist_user_tokens(user)
            record_user_event(
                user=user,
                actor=request.user,
                field_changed="password",
                old_value="",
                new_value="",
            )
            close_user_sockets(user.pk)
        return response


@admin.register(UserEvent)
class UserEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "actor",
        "field_changed",
        "old_value",
        "new_value",
        "created_at",
    )
    list_filter = ("field_changed",)
    search_fields = ("user__username", "actor__username", "field_changed")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(User, UserAdmin)
