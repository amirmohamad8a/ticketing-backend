from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from accounts.models import User


class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + ((None, {"fields": ("role", "phone", "avatar")}),)
    add_fieldsets = DjangoUserAdmin.add_fieldsets + ((None, {"fields": ("role", "phone")}),)
    list_display = DjangoUserAdmin.list_display + ("role", "phone")
    list_filter = DjangoUserAdmin.list_filter + ("role",)
    search_fields = DjangoUserAdmin.search_fields + ("phone",)


admin.site.register(User, UserAdmin)
