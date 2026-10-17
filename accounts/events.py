from enum import StrEnum

from accounts.models import UserEvent


class UserEventField(StrEnum):
    ROLE = "role"
    IS_ACTIVE = "is_active"
    IS_STAFF = "is_staff"
    IS_SUPERUSER = "is_superuser"
    PASSWORD = "password"
    GROUPS = "groups"
    USER_PERMISSIONS = "user_permissions"
    CREATED = "created"


def _flag(value):
    return "true" if value else "false"


flag = _flag


def record_user_event(user, actor, field_changed, old_value, new_value):
    return UserEvent.objects.create(
        user=user,
        actor=actor,
        field_changed=field_changed,
        old_value=old_value,
        new_value=new_value,
    )
