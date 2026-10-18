from django.urls import path

from audit.views import AuditLogView

urlpatterns = [
    path("audit/", AuditLogView.as_view(), name="audit-log"),
]
