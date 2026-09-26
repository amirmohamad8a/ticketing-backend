from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from accounts.models import User


class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + ((None, {"fields": ("role",)}),)
    add_fieldsets = DjangoUserAdmin.add_fieldsets + ((None, {"fields": ("role",)}),)
    list_display = DjangoUserAdmin.list_display + ("role",)
    list_filter = DjangoUserAdmin.list_filter + ("role",)


admin.site.register(User, UserAdmin)
