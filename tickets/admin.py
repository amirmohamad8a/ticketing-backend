from django.contrib import admin
from django.db import transaction

from tickets.events import RESTORED_FIELD, record_event
from tickets.models import (
    Attachment,
    CannedReply,
    Comment,
    ConversationRead,
    Tag,
    Ticket,
    TicketEvent,
    TicketRating,
)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "color", "updated_at")
    list_filter = ("color",)
    search_fields = ("name",)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "status",
        "priority",
        "channel",
        "customer",
        "visitor",
        "assignee",
        "first_response_due_at",
        "is_deleted",
        "created_at",
    )
    list_filter = ("status", "priority", "channel", "is_deleted")
    search_fields = (
        "title",
        "description",
        "customer__username",
        "visitor__name",
        "assignee__username",
    )
    readonly_fields = (
        "title",
        "description",
        "status",
        "priority",
        "channel",
        "customer",
        "visitor",
        "site",
        "assignee",
        "tags",
        "first_response_due_at",
        "first_response_at",
        "resolved_at",
        "is_deleted",
        "deleted_at",
        "created_at",
        "updated_at",
    )
    actions = ["restore_selected"]

    def get_queryset(self, request):
        return Ticket.all_objects.all()

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Restore selected tickets")
    def restore_selected(self, request, queryset):
        restored = 0
        for ticket in queryset.filter(is_deleted=True):
            with transaction.atomic():
                ticket.restore()
                record_event(
                    ticket=ticket,
                    actor=request.user,
                    field_changed=RESTORED_FIELD,
                    old_value="",
                    new_value="",
                )
                restored += 1
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

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("id", "ticket", "kind", "author", "visitor", "is_internal", "created_at")
    list_filter = ("kind", "is_internal")
    search_fields = ("body", "ticket__title", "author__username", "visitor__name")
    autocomplete_fields = ("ticket", "author", "visitor")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ConversationRead)
class ConversationReadAdmin(admin.ModelAdmin):
    list_display = ("id", "ticket", "user", "visitor", "last_read_comment_id", "updated_at")
    search_fields = ("ticket__title", "user__username", "visitor__name")
    autocomplete_fields = ("ticket", "user", "visitor")


@admin.register(TicketRating)
class TicketRatingAdmin(admin.ModelAdmin):
    list_display = ("id", "ticket", "score", "created_at")
    list_filter = ("score",)
    search_fields = ("ticket__title", "comment")
    autocomplete_fields = ("ticket",)

    def has_change_permission(self, request, obj=None):
        return False


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
    readonly_fields = (
        "ticket",
        "comment",
        "file",
        "original_name",
        "uploaded_by",
        "size",
        "content_type",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CannedReply)
class CannedReplyAdmin(admin.ModelAdmin):
    list_display = ("id", "shortcut", "title", "updated_at")
    search_fields = ("shortcut", "title", "body")
