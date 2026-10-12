from accounts.models import UserEvent


def record_user_event(user, actor, field_changed, old_value, new_value):
    return UserEvent.objects.create(
        user=user,
        actor=actor,
        field_changed=field_changed,
        old_value=old_value,
        new_value=new_value,
    )
