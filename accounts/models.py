import os
import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

from accounts.validators import validate_iranian_mobile

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

    def __str__(self):
        return self.username
