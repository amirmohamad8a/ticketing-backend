from rest_framework.throttling import UserRateThrottle


class ExportThrottle(UserRateThrottle):
    scope = "export"
