import secrets

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from chat.validators import validate_hex_color, validate_origin_list
from core.models import TimeStampedModel


def generate_site_key():
    return secrets.token_urlsafe(24)


class Site(TimeStampedModel):
    class Position(models.TextChoices):
        BOTTOM_RIGHT = "bottom_right", "Bottom right"
        BOTTOM_LEFT = "bottom_left", "Bottom left"

    name = models.CharField(max_length=100)
    key = models.CharField(max_length=64, unique=True, default=generate_site_key, editable=False)
    allowed_origins = models.JSONField(default=list, blank=True, validators=[validate_origin_list])
    is_active = models.BooleanField(default=True)
    greeting = models.CharField(max_length=500, blank=True, default="")
    primary_color = models.CharField(
        max_length=7, default="#2563eb", validators=[validate_hex_color]
    )
    position = models.CharField(
        max_length=20, choices=Position.choices, default=Position.BOTTOM_RIGHT
    )
    offline_timeout_minutes = models.PositiveSmallIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(1440)]
    )
    require_name = models.BooleanField(default=False)
    require_contact = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name

    def rotate_key(self):
        self.key = generate_site_key()
        self.save(update_fields=["key", "updated_at"])
