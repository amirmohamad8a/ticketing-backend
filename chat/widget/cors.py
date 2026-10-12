from django.dispatch import receiver

from corsheaders.signals import check_request_enabled

WIDGET_PATH_PREFIX = "/api/widget/"


@receiver(check_request_enabled)
def allow_widget_requests(sender, request, **kwargs):
    return request.path.startswith(WIDGET_PATH_PREFIX)
