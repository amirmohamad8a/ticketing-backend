from django.utils.translation import gettext_lazy as _

from rest_framework import status
from rest_framework.exceptions import APIException


class TicketAlreadyAssigned(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = _("This ticket is already assigned to someone else.")
    default_code = "ticket_already_assigned"


class TicketNotResolved(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = _("A ticket can only be rated after it has been resolved.")
    default_code = "ticket_not_resolved"


class TicketAlreadyRated(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = _("This ticket has already been rated.")
    default_code = "ticket_already_rated"
