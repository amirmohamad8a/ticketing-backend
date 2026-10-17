import hashlib

from rest_framework.exceptions import APIException
from rest_framework.throttling import SimpleRateThrottle

from accounts.models import User


class LoginUsernameThrottle(SimpleRateThrottle):
    scope = "login_username"

    def get_cache_key(self, request, view):
        username = self._username(request)
        if not username:
            return None
        raw = f"{username}|{self.get_ident(request)}"
        ident = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": ident}

    @staticmethod
    def _username(request):
        try:
            data = request.data
        except APIException:
            return None
        value = data.get("username") if hasattr(data, "get") else None
        if not isinstance(value, str):
            return None
        return User.normalize_username(value).strip().lower()
