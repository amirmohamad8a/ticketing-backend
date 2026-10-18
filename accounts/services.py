from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _

from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.events import UserEventField, flag, record_user_event
from accounts.models import User
from accounts.signals import user_deactivated, user_demoted
from accounts.tokens import blacklist_user_tokens
from core.errors import DomainValidationError
from core.events import close_user_sockets


def apply_user_side_effects(
    user,
    actor,
    events=(),
    *,
    revoke_tokens=False,
    deactivated=False,
    demoted=False,
    close_sockets=False,
    close_user_sockets_fn=close_user_sockets,
):
    with transaction.atomic():
        if revoke_tokens:
            blacklist_user_tokens(user)
        if deactivated:
            user_deactivated.send(sender=User, user=user, actor=actor)
        elif demoted:
            user_demoted.send(sender=User, user=user, actor=actor)
        for field_changed, old_value, new_value in events:
            record_user_event(
                user=user,
                actor=actor,
                field_changed=field_changed,
                old_value=old_value,
                new_value=new_value,
            )
        if close_sockets:
            close_user_sockets_fn(user.pk)


def create_user(actor=None, changes=None, *, record_created=True, **fields):
    data = dict(changes or {})
    data.update(fields)
    try:
        with transaction.atomic():
            user = User.objects.create_user(**data)
            if record_created:
                record_user_event(
                    user=user,
                    actor=actor,
                    field_changed=UserEventField.CREATED,
                    old_value="",
                    new_value=user.role,
                )
    except IntegrityError:
        if User.objects.filter(username__iexact=data.get("username", "")).exists():
            raise DomainValidationError(
                {"username": _("A user with that username already exists.")}
            )
        raise
    return user


def update_user(user, actor, changes, *, close_user_sockets_fn=close_user_sockets):
    data = dict(changes)
    password = data.pop("password", None)

    events = []
    deactivated = False
    demoted = False
    close_sockets = False
    if "role" in data and data["role"] != user.role:
        events.append((UserEventField.ROLE, user.role, data["role"]))
        demoted = data["role"] == User.Role.CUSTOMER
        close_sockets = True
    if "is_active" in data and data["is_active"] != user.is_active:
        new_state = data["is_active"]
        events.append((UserEventField.IS_ACTIVE, flag(user.is_active), flag(new_state)))
        deactivated = not new_state
        close_sockets = True
    if password is not None:
        events.append((UserEventField.PASSWORD, "", ""))
        close_sockets = True

    with transaction.atomic():
        for attr, value in data.items():
            setattr(user, attr, value)
        if data:
            user.save()
        if password is not None:
            user.set_password(password)
            user.save(update_fields=["password"])
        apply_user_side_effects(
            user,
            actor,
            events,
            revoke_tokens=password is not None or deactivated,
            deactivated=deactivated,
            demoted=demoted,
            close_sockets=close_sockets,
            close_user_sockets_fn=close_user_sockets_fn,
        )
    return user


def change_own_password(user, new_password, *, close_user_sockets_fn=close_user_sockets):
    with transaction.atomic():
        user.set_password(new_password)
        user.save(update_fields=["password"])
        apply_user_side_effects(
            user,
            None,
            revoke_tokens=True,
            close_sockets=True,
            close_user_sockets_fn=close_user_sockets_fn,
        )
    return user


def reset_password(user, password=None, actor=None, *, close_user_sockets_fn=close_user_sockets):
    with transaction.atomic():
        if password is not None:
            user.set_password(password)
            user.save(update_fields=["password"])
        apply_user_side_effects(
            user,
            actor,
            [(UserEventField.PASSWORD, "", "")],
            revoke_tokens=True,
            close_sockets=True,
            close_user_sockets_fn=close_user_sockets_fn,
        )
    return user


def logout_user(refresh_token, user, *, close_user_sockets_fn=close_user_sockets):
    if not refresh_token:
        raise DomainValidationError({"refresh": _("Refresh token is required.")})
    try:
        token = RefreshToken(refresh_token)
    except TokenError:
        raise DomainValidationError({"refresh": _("Invalid or expired token.")})
    with transaction.atomic():
        token.blacklist()
        close_user_sockets_fn(user.pk)
