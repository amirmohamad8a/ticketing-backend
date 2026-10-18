from django.utils.translation import gettext_lazy as _

from rest_framework import status

from core.errors import DomainError


class TicketAlreadyAssigned(DomainError):
    status_code = status.HTTP_409_CONFLICT
    code = "ticket_already_assigned"
    default_code = "ticket_already_assigned"
    default_message = _("This ticket is already assigned to someone else.")


class TicketNotResolved(DomainError):
    status_code = status.HTTP_409_CONFLICT
    code = "ticket_not_resolved"
    default_code = "ticket_not_resolved"
    default_message = _("A ticket can only be rated after it has been resolved.")


class TicketAlreadyRated(DomainError):
    status_code = status.HTTP_409_CONFLICT
    code = "ticket_already_rated"
    default_code = "ticket_already_rated"
    default_message = _("This ticket has already been rated.")
