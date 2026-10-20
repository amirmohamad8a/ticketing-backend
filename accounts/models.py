import os
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from accounts.validators import validate_iranian_mobile
from core.models import AuditEvent
from core.uploads import AVATAR_UPLOAD_POLICY

AVATAR_EXTENSIONS = AVATAR_UPLOAD_POLICY.extensions


def avatar_upload_path(instance, filename):
    extension = os.path.splitext(filename)[1].lower()
    if extension not in AVATAR_EXTENSIONS:
        extension = ""
    return f"avatars/{uuid.uuid4().hex}{extension}"


class UserManager(DjangoUserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    AVATAR_MAX_SIZE_BYTES = AVATAR_UPLOAD_POLICY.max_size_bytes
    AVATAR_CONTENT_TYPES = AVATAR_UPLOAD_POLICY.content_type_extensions
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

    objects = UserManager()

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        constraints = [
            models.UniqueConstraint(Lower("username"), name="user_username_ci_unique"),
        ]

    def __str__(self):
        return self.username


class UserEvent(AuditEvent):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="user_events_made",
    )

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["created_at", "id"], name="userevent_created_id_idx"),
        ]

    def __str__(self):
        return f"User #{self.user_id} {self.field_changed}: {self.old_value} -> {self.new_value}"
