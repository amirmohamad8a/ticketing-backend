import uuid

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import AppendOnlyModel, SoftDeleteModel, TimeStampedModel
from core.search import build_search_vector
from tickets.sla import compute_first_response_due_at
from tickets.validators import (
    MAX_BODY_LENGTH,
    MAX_SHORTCUT_LENGTH,
    MAX_TAG_NAME_LENGTH,
    normalize_tag_name,
    validate_shortcut,
)

TICKET_SEARCH_FIELDS = ("title", "description")
COMMENT_SEARCH_FIELDS = ("body",)
RATING_MIN_SCORE = 1
RATING_MAX_SCORE = 5
RATING_MAX_COMMENT_LENGTH = 1000


def attachment_upload_path(instance, filename):
    extension = Attachment.CONTENT_TYPE_EXTENSIONS.get(instance.content_type, "")
    return f"attachments/{timezone.localdate():%Y/%m/%d}/{uuid.uuid4().hex}{extension}"


class Tag(TimeStampedModel):
    class Color(models.TextChoices):
        GRAY = "gray", "Gray"
        RED = "red", "Red"
        ORANGE = "orange", "Orange"
        YELLOW = "yellow", "Yellow"
        GREEN = "green", "Green"
        TEAL = "teal", "Teal"
        BLUE = "blue", "Blue"
        PURPLE = "purple", "Purple"
        PINK = "pink", "Pink"

    name = models.CharField(max_length=MAX_TAG_NAME_LENGTH)
    color = models.CharField(max_length=10, choices=Color.choices, default=Color.GRAY)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="tag_unique_name_ci"),
        ]

    def clean(self):
        self.name = normalize_tag_name(self.name)

    def __str__(self):
        return self.name


class Ticket(SoftDeleteModel, TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        WAITING_ON_CUSTOMER = "waiting_on_customer", "Waiting on Customer"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Channel(models.TextChoices):
        PORTAL = "portal", "Portal"
        CHAT = "chat", "Chat"
        OFFLINE_FORM = "offline_form", "Offline form"

    STATUS_TRANSITIONS = {
        Status.OPEN: {Status.IN_PROGRESS},
        Status.IN_PROGRESS: {Status.WAITING_ON_CUSTOMER, Status.RESOLVED, Status.OPEN},
        Status.WAITING_ON_CUSTOMER: {Status.IN_PROGRESS, Status.RESOLVED},
        Status.RESOLVED: {Status.CLOSED, Status.IN_PROGRESS},
        Status.CLOSED: {Status.IN_PROGRESS},
    }
    FINISHED_STATUSES = (Status.RESOLVED, Status.CLOSED)

    title = models.CharField(max_length=255)
    description = models.TextField()
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.PORTAL)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tickets",
    )
    visitor = models.ForeignKey(
        "chat.Visitor",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tickets",
    )
    site = models.ForeignKey(
        "chat.Site",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tickets",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="tickets")
    first_response_due_at = models.DateTimeField(
        null=True, blank=True, editable=False, db_index=True
    )
    first_response_at = models.DateTimeField(null=True, blank=True, editable=False)
    resolved_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(customer__isnull=False, visitor__isnull=True)
                    | models.Q(customer__isnull=True, visitor__isnull=False)
                ),
                name="ticket_exactly_one_owner",
            )
        ]
        indexes = [
            GinIndex(build_search_vector(*TICKET_SEARCH_FIELDS), name="ticket_search_gin"),
            models.Index(fields=["-created_at", "-id"], name="ticket_created_id_desc_idx"),
        ]

    def clean(self):
        if bool(self.customer_id) == bool(self.visitor_id):
            raise ValidationError(_("Ticket must belong to exactly one of customer or visitor."))

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is None or "priority" in update_fields:
            self.first_response_due_at = compute_first_response_due_at(
                self.priority, self.created_at or timezone.now()
            )
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "first_response_due_at"}
        super().save(*args, **kwargs)

    def __str__(self):
        return f"#{self.pk} {self.title}"


class TicketEvent(AppendOnlyModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_events",
    )
    field_changed = models.CharField(max_length=50)
    old_value = models.CharField(max_length=255, blank=True, default="")
    new_value = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["created_at", "id"], name="ticketevent_created_id_idx"),
        ]

    def __str__(self):
        return (
            f"Ticket #{self.ticket_id} {self.field_changed}: {self.old_value} -> {self.new_value}"
        )


class Comment(TimeStampedModel):
    class Kind(models.TextChoices):
        MESSAGE = "message", "Message"
        SYSTEM = "system", "System"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="comments",
    )
    visitor = models.ForeignKey(
        "chat.Visitor",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="comments",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.MESSAGE)
    client_msg_id = models.CharField(max_length=64, null=True, blank=True)
    body = models.TextField()
    is_internal = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["ticket", "client_msg_id"],
                name="comment_unique_client_msg_id_per_ticket",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(kind="system")
                    | models.Q(author__isnull=False, visitor__isnull=True)
                    | models.Q(author__isnull=True, visitor__isnull=False)
                ),
                name="comment_message_exactly_one_sender",
            ),
        ]
        indexes = [
            GinIndex(build_search_vector(*COMMENT_SEARCH_FIELDS), name="comment_search_gin"),
            models.Index(fields=["ticket", "id"], name="comment_ticket_id_idx"),
        ]

    def clean(self):
        if self.kind != self.Kind.SYSTEM and bool(self.author_id) == bool(self.visitor_id):
            raise ValidationError(_("A message must have exactly one of author or visitor."))

    def __str__(self):
        return f"Comment #{self.pk} on Ticket #{self.ticket_id}"


class ConversationRead(TimeStampedModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="reads")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conversation_reads",
    )
    visitor = models.ForeignKey(
        "chat.Visitor",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conversation_reads",
    )
    last_read_comment_id = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["ticket", "user"],
                name="conversationread_unique_ticket_user",
            ),
            models.UniqueConstraint(
                fields=["ticket", "visitor"],
                name="conversationread_unique_ticket_visitor",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(user__isnull=False, visitor__isnull=True)
                    | models.Q(user__isnull=True, visitor__isnull=False)
                ),
                name="conversationread_exactly_one_reader",
            ),
        ]

    def clean(self):
        if bool(self.user_id) == bool(self.visitor_id):
            raise ValidationError(_("A read state must belong to exactly one of user or visitor."))

    def __str__(self):
        return f"Read state of Ticket #{self.ticket_id} up to Comment #{self.last_read_comment_id}"


class TicketRating(TimeStampedModel):
    ticket = models.OneToOneField(Ticket, on_delete=models.CASCADE, related_name="rating")
    score = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(RATING_MIN_SCORE), MaxValueValidator(RATING_MAX_SCORE)]
    )
    comment = models.TextField(
        blank=True,
        default="",
        validators=[MaxLengthValidator(RATING_MAX_COMMENT_LENGTH)],
    )

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(score__gte=RATING_MIN_SCORE, score__lte=RATING_MAX_SCORE),
                name="ticketrating_score_between_1_and_5",
            )
        ]

    def __str__(self):
        return f"Rating {self.score}/{RATING_MAX_SCORE} for Ticket #{self.ticket_id}"


class Attachment(TimeStampedModel):
    MAX_SIZE_BYTES = 10 * 1024 * 1024
    CONTENT_TYPE_EXTENSIONS = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/zip": ".zip",
    }
    ALLOWED_CONTENT_TYPES = frozenset(CONTENT_TYPE_EXTENSIONS)

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
    )
    comment = models.ForeignKey(
        Comment,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
    )
    file = models.FileField(upload_to=attachment_upload_path)
    original_name = models.CharField(max_length=255, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attachments",
    )
    size = models.PositiveIntegerField()
    content_type = models.CharField(max_length=255)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(ticket__isnull=False, comment__isnull=True)
                    | models.Q(ticket__isnull=True, comment__isnull=False)
                ),
                name="attachment_exactly_one_parent",
            )
        ]

    def clean(self):
        if bool(self.ticket_id) == bool(self.comment_id):
            raise ValidationError(_("Attachment must belong to exactly one of ticket or comment."))

    def __str__(self):
        return f"Attachment #{self.pk} ({self.file.name})"


class CannedReply(TimeStampedModel):
    title = models.CharField(max_length=100)
    body = models.TextField(validators=[MaxLengthValidator(MAX_BODY_LENGTH)])
    shortcut = models.CharField(
        max_length=MAX_SHORTCUT_LENGTH, unique=True, validators=[validate_shortcut]
    )

    class Meta:
        ordering = ["shortcut", "id"]

    def __str__(self):
        return f"/{self.shortcut}"
