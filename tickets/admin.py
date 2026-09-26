from django.contrib import admin

from tickets.models import Ticket


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "priority", "customer", "assignee", "created_at")
    list_filter = ("status", "priority")
    search_fields = ("title", "description", "customer__username", "assignee__username")
    autocomplete_fields = ("customer", "assignee")
