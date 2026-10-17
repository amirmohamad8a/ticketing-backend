from django.contrib import admin
from django.contrib.admin.utils import unquote
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db import transaction
from django.http import HttpResponseRedirect

from accounts.events import record_user_event
from accounts.models import User, UserEvent
from accounts.tokens import blacklist_user_tokens
from realtime.events import close_user_sockets
from tickets.assignment import release_tickets

M2M_FIELDS = ("groups", "user_permissions")
VALUE_MAX_LENGTH = 255


def _flag(value):
    return "true" if value else "false"


def _m2m_labels(user, field):
    if field == "groups":
        return set(user.groups.values_list("name", flat=True))
    rows = user.user_permissions.values_list("content_type__app_label", "codename")
    return {f"{app_label}.{codename}" for app_label, codename in rows}


def _join(values):
    return ", ".join(sorted(values))[:VALUE_MAX_LENGTH]


class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        (None, {"fields": ("role", "phone", "avatar", "max_concurrent_chats")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + ((None, {"fields": ("role", "phone")}),)
    list_display = DjangoUserAdmin.list_display + ("role", "phone")
    list_filter = DjangoUserAdmin.list_filter + ("role",)
    search_fields = DjangoUserAdmin.search_fields + ("phone",)

    def has_delete_permission(self, request, obj=None):
        return False

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

        previous = User.objects.only("role", "is_active", "is_staff", "is_superuser").get(pk=obj.pk)
        events = []
        if previous.role != obj.role:
            events.append(("role", previous.role, obj.role))
        if previous.is_active != obj.is_active:
            events.append(("is_active", _flag(previous.is_active), _flag(obj.is_active)))
        if previous.is_staff != obj.is_staff:
            events.append(("is_staff", _flag(previous.is_staff), _flag(obj.is_staff)))
        if previous.is_superuser != obj.is_superuser:
            events.append(("is_superuser", _flag(previous.is_superuser), _flag(obj.is_superuser)))
        deactivated = previous.is_active and not obj.is_active
        demoted = previous.role != obj.role and obj.role == User.Role.CUSTOMER

        with transaction.atomic():
            super().save_model(request, obj, form, change)
            if deactivated:
                blacklist_user_tokens(obj)
            if deactivated or demoted:
                release_tickets(obj, actor)
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

    def save_related(self, request, form, formsets, change):
        user = form.instance
        before = {field: _m2m_labels(user, field) for field in M2M_FIELDS} if change else {}
        with transaction.atomic():
            super().save_related(request, form, formsets, change)
            if not change:
                return
            changed = False
            for field in M2M_FIELDS:
                after = _m2m_labels(user, field)
                if after == before[field]:
                    continue
                changed = True
                record_user_event(
                    user=user,
                    actor=request.user,
                    field_changed=field,
                    old_value=_join(before[field] - after),
                    new_value=_join(after - before[field]),
                )
            if changed:
                close_user_sockets(user.pk)

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
