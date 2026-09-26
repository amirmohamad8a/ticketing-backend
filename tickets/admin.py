from django.contrib import admin

from tickets.models import Attachment, Comment, Ticket, TicketEvent


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "priority", "customer", "assignee", "created_at")
    list_filter = ("status", "priority")
    search_fields = ("title", "description", "customer__username", "assignee__username")
    autocomplete_fields = ("customer", "assignee")


@admin.register(TicketEvent)
class TicketEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "ticket",
        "actor",
        "field_changed",
        "old_value",
        "new_value",
        "created_at",
    )
    list_filter = ("field_changed",)
    search_fields = ("ticket__title", "actor__username", "field_changed")
    autocomplete_fields = ("ticket", "actor")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("id", "ticket", "author", "is_internal", "created_at")
    list_filter = ("is_internal",)
    search_fields = ("body", "ticket__title", "author__username")
    autocomplete_fields = ("ticket", "author")


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "ticket",
        "comment",
        "uploaded_by",
        "content_type",
        "size",
        "created_at",
    )
    list_filter = ("content_type",)
    search_fields = ("file", "ticket__title", "uploaded_by__username")
    autocomplete_fields = ("ticket", "comment", "uploaded_by")
