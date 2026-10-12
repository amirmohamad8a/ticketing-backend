from django.contrib import admin

from chat.models import Site


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "key", "is_active", "position", "created_at")
    list_filter = ("is_active", "position")
    search_fields = ("name", "key")
    readonly_fields = ("key", "created_at", "updated_at")
