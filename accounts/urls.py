from django.urls import path

from accounts.views import LogoutView

urlpatterns = [
    path("logout/", LogoutView.as_view(), name="logout"),
]
