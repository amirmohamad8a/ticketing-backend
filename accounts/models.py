import os
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from accounts.validators import validate_iranian_mobile
from core.models import AppendOnlyModel

AVATAR_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})


def avatar_upload_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    if extension not in AVATAR_EXTENSIONS:
        extension = ""
    return f"avatars/{uuid.uuid4().hex}{extension}"


class User(AbstractUser):
    AVATAR_MAX_SIZE_BYTES = 2 * 1024 * 1024
    AVATAR_CONTENT_TYPES = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }
    DEFAULT_MAX_CONCURRENT_CHATS = 5
    MAX_CONCURRENT_CHATS_LIMIT = 50

    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        AGENT = "agent", "Agent"
        ADMIN = "admin", "Admin"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)
    phone = models.CharField(
        max_length=11,
        unique=True,
        null=True,
        blank=True,
        validators=[validate_iranian_mobile],
    )
    avatar = models.ImageField(upload_to=avatar_upload_path, null=True, blank=True)
    max_concurrent_chats = models.PositiveSmallIntegerField(
        default=DEFAULT_MAX_CONCURRENT_CHATS,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_CONCURRENT_CHATS_LIMIT)],
    )
    last_chat_assigned_at = models.DateTimeField(null=True, blank=True, editable=False)

    def __str__(self):
        return self.username


class UserEvent(AppendOnlyModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_events_made",
    )
    field_changed = models.CharField(max_length=50)
    old_value = models.CharField(max_length=255, blank=True, default="")
    new_value = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["created_at", "id"], name="userevent_created_id_idx"),
        ]

    def __str__(self):
        return f"User #{self.user_id} {self.field_changed}: {self.old_value} -> {self.new_value}"
