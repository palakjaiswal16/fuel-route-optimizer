from django.apps import AppConfig


class RoutingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "routing"

    def ready(self):
        from .services import load_fuel_stations

        load_fuel_stations()
