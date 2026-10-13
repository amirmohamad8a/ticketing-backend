from django.urls import path

from stats.views import StatsView

urlpatterns = [
    path("stats/", StatsView.as_view(), name="stats"),
]
