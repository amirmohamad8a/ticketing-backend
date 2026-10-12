from drf_spectacular.extensions import OpenApiAuthenticationExtension


class LoggedJWTScheme(OpenApiAuthenticationExtension):
    target_class = "core.authentication.LoggedJWTAuthentication"
    name = "jwtAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
