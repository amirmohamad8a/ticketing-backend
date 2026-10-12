from django.contrib import admin

from tickets.models import Attachment, Comment, Ticket, TicketEvent


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "status",
        "priority",
        "customer",
        "assignee",
        "is_deleted",
        "created_at",
    )
    list_filter = ("status", "priority", "is_deleted")
    search_fields = ("title", "description", "customer__username", "assignee__username")
    autocomplete_fields = ("customer", "assignee")
    readonly_fields = ("is_deleted", "deleted_at")
    actions = ["restore_selected"]

    def get_queryset(self, request):
        return Ticket.all_objects.all()

    @admin.action(description="Restore selected tickets")
    def restore_selected(self, request, queryset):
        restored = queryset.restore()
        self.message_user(request, f"Restored {restored} ticket(s).")


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
        "original_name",
        "uploaded_by",
        "content_type",
        "size",
        "created_at",
    )
    list_filter = ("content_type",)
    search_fields = ("file", "original_name", "ticket__title", "uploaded_by__username")
    autocomplete_fields = ("ticket", "comment", "uploaded_by")
