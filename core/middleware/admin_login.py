from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.utils.translation import gettext

from rest_framework.throttling import BaseThrottle

ADMIN_LOGIN_CACHE_PREFIX = "admin_login_attempt"


class AdminLoginThrottleMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._is_login_attempt(request) and self._too_many_attempts(request):
            return HttpResponse(
                gettext("Too many login attempts. Please try again later."),
                status=429,
                content_type="text/plain",
            )
        return self.get_response(request)

    @staticmethod
    def _is_login_attempt(request):
        return request.method == "POST" and request.path_info == settings.ADMIN_LOGIN_PATH

    @staticmethod
    def _too_many_attempts(request):
        max_attempts = settings.ADMIN_LOGIN_MAX_ATTEMPTS
        if max_attempts <= 0:
            return False
        ident = BaseThrottle().get_ident(request) or "unknown"
        key = f"{ADMIN_LOGIN_CACHE_PREFIX}:{ident}"
        window = settings.ADMIN_LOGIN_WINDOW_SECONDS
        try:
            if cache.add(key, 1, window):
                return False
            attempts = cache.incr(key)
        except ValueError:
            cache.set(key, 1, window)
            return False
        return attempts > max_attempts
