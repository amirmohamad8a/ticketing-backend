from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from accounts.models import User, UserEvent


class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        (None, {"fields": ("role", "phone", "avatar", "max_concurrent_chats")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + ((None, {"fields": ("role", "phone")}),)
    list_display = DjangoUserAdmin.list_display + ("role", "phone")
    list_filter = DjangoUserAdmin.list_filter + ("role",)
    search_fields = DjangoUserAdmin.search_fields + ("phone",)


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
