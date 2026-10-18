from rest_framework_simplejwt.authentication import JWTAuthentication

from core.logs import user_id_var


class LoggedJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            user_id_var.set(result[0].pk)
        return result
