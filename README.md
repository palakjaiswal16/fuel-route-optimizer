# Fuel Route API

Django API for a backend engineering assessment. It accepts a start and finish location inside the USA, gets a driving route, finds cost-effective fuel stops from the supplied truck-stop price CSV, and returns route geometry plus an estimated fuel bill for a 10 MPG vehicle with a 500 mile range.

## Stack

- Django 6.0.6
- OpenStreetMap Nominatim for start/end geocoding
- OSRM public route API for driving route geometry
- `geonamescache` for offline US city coordinates, so fuel stops from the CSV can be placed without thousands of live geocoding calls

The current Django latest official version is 6.0.6. OSRM is free/open source, and Nominatim is suitable for light/occasional use with a custom user agent. For production volume, run OSRM/Nominatim yourself or swap in a commercial provider.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py test
python manage.py runserver
```

## API

`POST /api/route-plan/`

```json
{
  "start": "Dallas, TX",
  "finish": "Phoenix, AZ"
}
```

The response includes:

- `route.geometry`: GeoJSON LineString suitable for drawing on a map.
- `fuel_plan.stops`: selected truck stops with route mile, price, gallons, and estimated spend.
- `fuel_plan.total_spend`: total estimated dollars spent on route fuel.
- `map_preview_url`: browser URL that draws the returned route and fuel stops on a Leaflet/OpenStreetMap preview.

## Map Preview

Run the server and open:

```text
http://127.0.0.1:8000/map/
```

This Leaflet page calls the same API, draws the route on OpenStreetMap tiles, and places markers for the selected fuel stops. It is included only as a visual demo; the required deliverable is still the JSON API.

## Notes For Reviewers

- The API makes two geocoding calls for uncached start/end locations and one OSRM route call. Geocodes are cached in `data/geocode-cache.json`.
- Common `City, ST` inputs are resolved from an offline city index, so those requests skip Nominatim entirely.
- Full route plans and OSRM route responses are cached for 24 hours. Repeated identical requests are served from memory and include `performance.cache = "hit"`.
- On local testing, Dallas to Phoenix returned in about 1.8 seconds on the first request and about 60 ms on a repeated request from cache. The exact first-request time depends mostly on OSRM network latency.
- The CSV has no exact station coordinates, so station lat/lon values are approximated from their city/state. This keeps the API fast and avoids bulk geocoding, but a production system should enrich the fuel-price table with exact station coordinates.
- The optimizer uses dynamic programming over stations inside a route corridor and respects the 500 mile range limit.
