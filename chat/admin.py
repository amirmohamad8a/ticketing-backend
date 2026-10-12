from django.contrib import admin

from chat.models import Site, Visitor


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "key", "is_active", "position", "created_at")
    list_filter = ("is_active", "position")
    search_fields = ("name", "key")
    readonly_fields = ("key", "created_at", "updated_at")


@admin.register(Visitor)
class VisitorAdmin(admin.ModelAdmin):
    list_display = ("id", "site", "name", "phone", "email", "last_seen_at", "created_at")
    list_filter = ("site",)
    search_fields = ("name", "phone", "email")
    autocomplete_fields = ("site",)
    readonly_fields = ("created_at",)
