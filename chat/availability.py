from accounts.models import User

STAFF_ROLES = (User.Role.AGENT, User.Role.ADMIN)


def agents_available(site):
    return User.objects.filter(is_active=True, role__in=STAFF_ROLES).exists()
