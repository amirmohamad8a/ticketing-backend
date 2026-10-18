from config.settings.environment import env

NUM_PROXIES = env.int("NUM_PROXIES", default=0)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("core.authentication.LoggedJWTAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.exceptions.custom_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "120/min",
        "user": "300/min",
        "login": "30/min",
        "login_username": "20/hour",
        "login_username_global": "120/hour",
        "register": "30/hour",
        "password_change": "5/hour",
        "user_management": "60/min",
        "site_management": "60/min",
        "download": "300/min",
        "export": "10/min",
        "attachment_upload": "60/hour",
        "ws_ticket": "30/min",
        "widget_ip": "240/min",
        "widget_visitor": "90/min",
        "widget_start": "60/hour",
        "widget_upload": "30/hour",
    },
    "NUM_PROXIES": NUM_PROXIES,
}
