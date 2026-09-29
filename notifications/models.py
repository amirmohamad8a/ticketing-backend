from django.db import models

from core.models import TimeStampedModel


class NotificationLog(TimeStampedModel):
    idempotency_key = models.CharField(max_length=100, unique=True)
    event = models.ForeignKey(
        "tickets.TicketEvent",
        on_delete=models.CASCADE,
        related_name="notification_logs",
    )

    def __str__(self):
        return self.idempotency_key
