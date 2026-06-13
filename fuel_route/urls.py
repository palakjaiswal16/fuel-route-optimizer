from django.urls import path

from routing.views import map_preview, route_plan

urlpatterns = [
    path("api/route-plan/", route_plan, name="route-plan"),
    path("map/", map_preview, name="map-preview"),
]
