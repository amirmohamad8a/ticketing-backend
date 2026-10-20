from django.utils.translation import gettext_lazy as _

from rest_framework import exceptions, status


class DomainError(Exception):
    code = "error"
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = _("An error occurred.")

    def __init__(self, message=None, *, code=None, status_code=None, details=None):
        self.message = str(message if message is not None else self.default_message)
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details
        super().__init__(self.message)


def _messages(value):
    items = value if isinstance(value, (list, tuple)) else [value]
    return [str(item) for item in items]


class DomainValidationError(DomainError, exceptions.ValidationError):
    code = "validation_error"
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = _("Validation failed.")

    def __init__(self, field_errors=None, message=None):
        self.field_errors = {
            field: _messages(value) for field, value in (field_errors or {}).items()
        }
        self.message = str(message if message is not None else self.default_message)
        self.details = self.field_errors
        exceptions.ValidationError.__init__(self, self.field_errors)
