from django.apps import AppConfig


class StatsConfig(AppConfig):
    name = "stats"

    def ready(self):
        from core.metrics import register_scrape_collector
        from stats.metrics import DatabaseCollector

        register_scrape_collector(DatabaseCollector())
