from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET", "HEAD"])
@never_cache
def health(request):
    return JsonResponse({"status": "ok"})
