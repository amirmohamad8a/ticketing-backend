import hashlib
import logging

from rest_framework.exceptions import APIException
from rest_framework.throttling import SimpleRateThrottle

from accounts.models import User
from core.counters import increment_fixed_window
from core.metrics import login_global_budget_exceeded

logger = logging.getLogger(__name__)


class LoginUsernameThrottle(SimpleRateThrottle):
    scope = "login_username"
    global_scope = "login_username_global"
    retry_after = None

    def get_cache_key(self, request, view):
        username = self._username(request)
        if not username:
            return None
        return self._key(self.scope, f"{username}|{self.get_ident(request)}")

    def allow_request(self, request, view):
        username = self._username(request)
        if not username:
            return True
        if not self._consume(self.scope, f"{username}|{self.get_ident(request)}"):
            return False
        if not self._consume(self.global_scope, username):
            logger.warning("Per-username global login budget spent")
            login_global_budget_exceeded.inc()
        return True

    def wait(self):
        return getattr(self, "retry_after", None)

    def _consume(self, scope, raw):
        rate = self.THROTTLE_RATES.get(scope)
        if not rate:
            return True
        num_requests, duration = self.parse_rate(rate)
        if num_requests is None:
            return True
        attempts = increment_fixed_window(self._key(scope, raw), duration)
        if attempts <= num_requests:
            return True
        self.retry_after = duration
        return False

    def _key(self, scope, raw):
        ident = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.cache_format % {"scope": scope, "ident": ident}

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
