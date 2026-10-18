def avatar_files():
    from accounts.models import User

    return User.objects.exclude(avatar="").values_list("avatar", flat=True)
