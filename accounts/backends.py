from django.contrib.auth import (
    acheck_password_with_timing_attack_mitigation,
    check_password_with_timing_attack_mitigation,
)
from django.contrib.auth.backends import ModelBackend
from django.views.decorators.debug import sensitive_variables

from accounts.models import User


class CaseInsensitiveModelBackend(ModelBackend):
    @sensitive_variables("password")
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if username is None or password is None:
            return None
        user = User.objects.filter(username__iexact=User.normalize_username(username)).first()
        if check_password_with_timing_attack_mitigation(user, password) and (
            self.user_can_authenticate(user)
        ):
            return user
        return None

    @sensitive_variables("password")
    async def aauthenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if username is None or password is None:
            return None
        user = await User.objects.filter(
            username__iexact=User.normalize_username(username)
        ).afirst()
        if await acheck_password_with_timing_attack_mitigation(user, password) and (
            self.user_can_authenticate(user)
        ):
            return user
        return None
