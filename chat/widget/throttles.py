from rest_framework.throttling import SimpleRateThrottle

from chat.models import Visitor


class WidgetIPThrottle(SimpleRateThrottle):
    scope = "widget_ip"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class WidgetVisitorThrottle(SimpleRateThrottle):
    scope = "widget_visitor"

    def get_cache_key(self, request, view):
        visitor = request.auth
        if not isinstance(visitor, Visitor):
            return None
        return self.cache_format % {"scope": self.scope, "ident": visitor.pk}


class WidgetStartThrottle(WidgetIPThrottle):
    scope = "widget_start"

    def allow_request(self, request, view):
        if isinstance(request.auth, Visitor):
            return True
        return super().allow_request(request, view)


class WidgetUploadThrottle(WidgetVisitorThrottle):
    scope = "widget_upload"
