from datetime import timedelta

from django.conf import settings


def first_response_minutes(priority):
    return settings.SLA_FIRST_RESPONSE_MINUTES[priority]


def compute_first_response_due_at(priority, started_at):
    return started_at + timedelta(minutes=first_response_minutes(priority))
