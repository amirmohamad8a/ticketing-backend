from django.utils.translation import gettext as _

from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler

from core.errors import DomainError


def custom_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
            status=exc.status_code,
        )

    response = exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, exceptions.ValidationError):
        code = "validation_error"
        message = _("Validation failed.")
        details = response.data
    else:
        data = response.data
        detail = data.get("detail") if isinstance(data, dict) else None
        code = getattr(detail, "code", "error")
        message = str(detail) if detail is not None else _("An error occurred.")
        details = None

    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response
