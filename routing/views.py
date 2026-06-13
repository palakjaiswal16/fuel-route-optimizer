from __future__ import annotations

import json
import time
from urllib.parse import urlencode

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from requests import RequestException

from .services import RoutingError, build_route_plan


@csrf_exempt
def route_plan(request):
    started = time.perf_counter()
    if request.method != "POST":
        return JsonResponse({"detail": "POST required."}, status=405)

    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Request body must be valid JSON."}, status=400)

    start = str(payload.get("start", "")).strip()
    finish = str(payload.get("finish", "")).strip()
    if not start or not finish:
        return JsonResponse({"detail": "Both 'start' and 'finish' are required."}, status=400)

    try:
        plan = build_route_plan(start, finish)
    except RoutingError as exc:
        return JsonResponse({"detail": str(exc)}, status=422)
    except RequestException as exc:
        return JsonResponse({"detail": f"Map service request failed: {exc}"}, status=502)

    plan["map_preview_url"] = request.build_absolute_uri(
        f"/map/?{urlencode({'start': start, 'finish': finish})}"
    )
    plan.setdefault("performance", {})
    plan["performance"]["response_time_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return JsonResponse(plan)


def map_preview(request):
    return HttpResponse(
        """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Fuel Route Map</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    html, body { height: 100%; margin: 0; font-family: Arial, sans-serif; }
    body { display: grid; grid-template-rows: auto 1fr; }
    form { display: flex; gap: 8px; padding: 12px; border-bottom: 1px solid #ddd; align-items: center; flex-wrap: wrap; }
    input { padding: 8px 10px; min-width: 220px; border: 1px solid #bbb; border-radius: 4px; }
    button { padding: 8px 12px; border: 1px solid #222; background: #222; color: white; border-radius: 4px; cursor: pointer; }
    #summary { font-size: 14px; color: #333; }
    #map { min-height: 0; }
  </style>
</head>
<body>
  <form id="route-form">
    <input id="start" value="Dallas, TX" aria-label="Start location">
    <input id="finish" value="Phoenix, AZ" aria-label="Finish location">
    <button type="submit">Route</button>
    <span id="summary"></span>
  </form>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const params = new URLSearchParams(window.location.search);
    document.getElementById("start").value = params.get("start") || "Dallas, TX";
    document.getElementById("finish").value = params.get("finish") || "Phoenix, AZ";

    const map = L.map("map").setView([39.5, -98.35], 4);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors"
    }).addTo(map);

    let routeLayer;
    let markerLayer = L.layerGroup().addTo(map);

    async function drawRoute(event) {
      event && event.preventDefault();
      document.getElementById("summary").textContent = "Loading...";
      markerLayer.clearLayers();
      if (routeLayer) map.removeLayer(routeLayer);

      const response = await fetch("/api/route-plan/", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          start: document.getElementById("start").value,
          finish: document.getElementById("finish").value
        })
      });
      const data = await response.json();
      if (!response.ok) {
        document.getElementById("summary").textContent = data.detail || "Request failed";
        return;
      }

      routeLayer = L.geoJSON(data.route.geometry, {style: {color: "#1264a3", weight: 5}}).addTo(map);
      map.fitBounds(routeLayer.getBounds(), {padding: [24, 24]});

      L.marker([data.start.latitude, data.start.longitude]).bindPopup("Start: " + data.start.label).addTo(markerLayer);
      L.marker([data.finish.latitude, data.finish.longitude]).bindPopup("Finish: " + data.finish.label).addTo(markerLayer);
      data.fuel_plan.stops.forEach((stop, index) => {
        L.circleMarker([stop.latitude, stop.longitude], {
          radius: 8,
          color: "#0a7f45",
          fillColor: "#0a7f45",
          fillOpacity: 0.9
        }).bindPopup(
          `<strong>Fuel stop ${index + 1}</strong><br>${stop.name}<br>${stop.city}, ${stop.state}<br>` +
          `$${stop.price_per_gallon}/gal<br>Spend: $${stop.estimated_spend}`
        ).addTo(markerLayer);
      });

      document.getElementById("summary").textContent =
        `${data.route.distance_miles} miles | ${data.fuel_plan.stops.length} stops | $${data.fuel_plan.total_spend}`;
    }

    document.getElementById("route-form").addEventListener("submit", drawRoute);
    drawRoute();
  </script>
</body>
</html>
        """,
        content_type="text/html",
    )
