from django.utils.translation import gettext_lazy as _

from accounts.models import User
from core.errors import DomainValidationError
from tickets.models import Ticket
from tickets.validators import MAX_TICKET_TAGS


def validate_status_transition(ticket, new_status):
    if new_status == ticket.status:
        return new_status
    allowed = Ticket.STATUS_TRANSITIONS.get(ticket.status, set())
    if new_status not in allowed:
        message = _("Cannot transition status from '%(current)s' to '%(new)s'.")
        raise DomainValidationError(
            {
                "status": [
                    message % {"current": ticket.status, "new": new_status},
                ]
            }
        )
    return new_status


def validate_assignee(assignee, current_assignee=None):
    if assignee is None:
        return assignee
    if current_assignee is not None and assignee.pk == current_assignee.pk:
        return assignee
    if assignee.role == User.Role.CUSTOMER:
        raise DomainValidationError(
            {"assignee": [_("Tickets can only be assigned to an agent or admin.")]}
        )
    if not assignee.is_active:
        raise DomainValidationError(
            {"assignee": [_("Tickets cannot be assigned to an inactive user.")]}
        )
    return assignee


def validate_tags(tags):
    value = list(dict.fromkeys(tags))
    if len(value) > MAX_TICKET_TAGS:
        message = _("A ticket can have at most %(max)s tags.")
        raise DomainValidationError({"tags": [message % {"max": MAX_TICKET_TAGS}]})
    return value
