from django.contrib.auth.models import AbstractUser
from django.db import models

from accounts.validators import validate_iranian_mobile


class User(AbstractUser):
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

    def __str__(self):
        return self.username
