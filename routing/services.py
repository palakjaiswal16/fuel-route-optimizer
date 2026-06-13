from __future__ import annotations

import csv
import copy
import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from typing import Any

import geonamescache
import requests
from django.conf import settings
from django.core.cache import cache

from .geo import cumulative_miles, haversine_miles, nearest_route_position, read_json, sample_route_points, write_json


STATE_CODES = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "Florida": "FL",
    "Georgia": "GA",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
}


@dataclass(frozen=True)
class Location:
    label: str
    lat: float
    lon: float


@dataclass(frozen=True)
class FuelStation:
    id: str
    name: str
    address: str
    city: str
    state: str
    price: Decimal
    lat: float
    lon: float
    route_mile: float = 0.0
    distance_from_route: float = 0.0

    def with_route_position(self, route_mile: float, distance_from_route: float) -> "FuelStation":
        return FuelStation(
            id=self.id,
            name=self.name,
            address=self.address,
            city=self.city,
            state=self.state,
            price=self.price,
            lat=self.lat,
            lon=self.lon,
            route_mile=route_mile,
            distance_from_route=distance_from_route,
        )


class RoutingError(Exception):
    pass


class RouteClient:
    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def geocode(self, query: str) -> Location:
        local_location = geocode_city_state_locally(query)
        if local_location:
            return local_location

        cache_path = Path(settings.GEOCODE_CACHE_PATH)
        cache = read_json(cache_path)
        cache_key = query.strip().lower()
        if cache_key in cache:
            cached = cache[cache_key]
            return Location(query, float(cached["lat"]), float(cached["lon"]))

        response = requests.get(
            settings.NOMINATIM_SEARCH_URL,
            params={"q": f"{query}, USA", "format": "jsonv2", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": settings.NOMINATIM_USER_AGENT},
            timeout=self.timeout,
        )
        response.raise_for_status()
        results = response.json()
        if not results:
            raise RoutingError(f"Could not geocode '{query}' inside the USA.")

        location = Location(query, float(results[0]["lat"]), float(results[0]["lon"]))
        cache[cache_key] = {"lat": location.lat, "lon": location.lon}
        write_json(cache_path, cache)
        return location

    def route(self, start: Location, finish: Location) -> dict[str, Any]:
        route_cache_key = make_cache_key(
            "route:v1",
            round(start.lat, 5),
            round(start.lon, 5),
            round(finish.lat, 5),
            round(finish.lon, 5),
        )
        cached = cache.get(route_cache_key)
        if cached:
            return copy.deepcopy(cached)

        url = settings.OSRM_ROUTE_URL.format(
            lon1=start.lon,
            lat1=start.lat,
            lon2=finish.lon,
            lat2=finish.lat,
        )
        response = requests.get(
            url,
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "Ok" or not payload.get("routes"):
            raise RoutingError("OSRM did not return a drivable route.")
        route = payload["routes"][0]
        route_payload = {
            "distance_miles": route["distance"] / 1609.344,
            "duration_minutes": route["duration"] / 60,
            "geometry": route["geometry"],
        }
        cache.set(route_cache_key, copy.deepcopy(route_payload), settings.ROUTE_CACHE_SECONDS)
        return route_payload


@lru_cache(maxsize=1)
def city_coordinate_index() -> dict[tuple[str, str], tuple[float, float]]:
    gc = geonamescache.GeonamesCache()
    cities = {}
    for city in gc.get_cities().values():
        if city.get("countrycode") != "US":
            continue
        admin_code = city.get("admin1code")
        name = city.get("name", "").strip().lower()
        if admin_code and name:
            cities[(name, admin_code.upper())] = (float(city["latitude"]), float(city["longitude"]))
    return cities


def normalize_query(query: str) -> str:
    return " ".join(query.strip().lower().split())


def make_cache_key(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def state_lookup() -> dict[str, str]:
    lookup = {code.lower(): code for code in STATE_CODES.values()}
    lookup.update({name.lower(): code for name, code in STATE_CODES.items()})
    return lookup


def geocode_city_state_locally(query: str) -> Location | None:
    cleaned = re.sub(r"\busa\b|\bunited states\b", "", query, flags=re.IGNORECASE).strip(" ,")
    match = re.match(r"^(?P<city>[A-Za-z .'-]+),\s*(?P<state>[A-Za-z .]+)$", cleaned)
    if not match:
        return None

    city = normalize_query(match.group("city"))
    state = state_lookup().get(normalize_query(match.group("state")))
    if not state:
        return None

    coordinates = city_coordinate_index().get((city, state))
    if not coordinates:
        return None

    lat, lon = coordinates
    return Location(query, lat, lon)


@lru_cache(maxsize=1)
def load_fuel_stations() -> tuple[FuelStation, ...]:
    stations = []
    coordinates = city_coordinate_index()
    csv_path = Path(settings.FUEL_PRICE_CSV)
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            key = (row["City"].strip().lower(), row["State"].strip().upper())
            if key not in coordinates:
                continue
            lat, lon = coordinates[key]
            stations.append(
                FuelStation(
                    id=row["OPIS Truckstop ID"].strip(),
                    name=row["Truckstop Name"].strip(),
                    address=row["Address"].strip(),
                    city=row["City"].strip(),
                    state=row["State"].strip().upper(),
                    price=Decimal(row["Retail Price"]).quantize(Decimal("0.001")),
                    lat=lat,
                    lon=lon,
                )
            )
    return tuple(dedupe_cheapest_station(stations))


def dedupe_cheapest_station(stations: list[FuelStation]) -> list[FuelStation]:
    by_key: dict[tuple[str, str, str, str], FuelStation] = {}
    for station in stations:
        key = (station.name.upper(), station.city.upper(), station.state.upper(), station.address.upper())
        if key not in by_key or station.price < by_key[key].price:
            by_key[key] = station
    return list(by_key.values())


def route_points_from_geometry(geometry: dict[str, Any]) -> list[tuple[float, float]]:
    return [(lat, lon) for lon, lat in geometry["coordinates"]]


def find_corridor_stations(
    route_points: list[tuple[float, float]],
    route_miles: list[float],
    corridor_miles: float,
) -> list[FuelStation]:
    bounds = (
        min(point[0] for point in route_points) - 1.5,
        max(point[0] for point in route_points) + 1.5,
        min(point[1] for point in route_points) - 1.5,
        max(point[1] for point in route_points) + 1.5,
    )
    sampled_route = list(sample_route_points(route_points, route_miles))
    rough_points = [point for point, _ in sampled_route]
    nearest_points = list(sample_route_points(route_points, route_miles, every_miles=5.0))
    nearest_route_points = [point for point, _ in nearest_points]
    nearest_route_miles = [mile for _, mile in nearest_points]
    candidates = []
    for station in load_fuel_stations():
        if not (bounds[0] <= station.lat <= bounds[1] and bounds[2] <= station.lon <= bounds[3]):
            continue
        rough_distance = min(haversine_miles((station.lat, station.lon), point) for point in rough_points)
        if rough_distance > corridor_miles + 25:
            continue
        distance, mile = nearest_route_position(
            (station.lat, station.lon),
            nearest_route_points,
            nearest_route_miles,
        )
        if distance <= corridor_miles:
            candidates.append(station.with_route_position(mile, distance))
    return sorted(candidates, key=lambda station: (station.route_mile, station.price))


def optimize_fuel_stops(
    stations: list[FuelStation],
    total_miles: float,
    max_range_miles: float,
    mpg: float,
) -> tuple[list[dict[str, Any]], Decimal]:
    if total_miles <= 0:
        return [], Decimal("0.00")

    useful = [station for station in stations if 0 <= station.route_mile <= total_miles]
    if not useful:
        raise RoutingError("No fuel stations from the price file were found near this route.")

    useful = sorted(useful, key=lambda station: (station.route_mile, station.price))
    if not any(station.route_mile <= max_range_miles for station in useful):
        raise RoutingError("No reachable fuel station was found within the first 500 miles.")

    nodes: list[FuelStation | None] = [*useful, None]
    miles = [station.route_mile for station in useful] + [total_miles]
    prices = [station.price for station in useful] + [Decimal("0")]
    count = len(miles)
    costs = [Decimal("Infinity")] * count
    previous: list[int | None] = [None] * count
    initial_leg_miles = [Decimal("0")] * count

    for index, station in enumerate(useful):
        if station.route_mile > max_range_miles:
            break
        initial_leg = Decimal(str(station.route_mile))
        costs[index] = (initial_leg / Decimal(str(mpg))) * station.price
        initial_leg_miles[index] = initial_leg

    for i in range(count):
        if costs[i].is_infinite():
            continue
        for j in range(i + 1, count):
            leg = miles[j] - miles[i]
            if leg > max_range_miles:
                break
            gallons = Decimal(str(leg / mpg))
            candidate = costs[i] + gallons * prices[i]
            if candidate < costs[j]:
                costs[j] = candidate
                previous[j] = i
                initial_leg_miles[j] = initial_leg_miles[i]

    if costs[-1].is_infinite():
        raise RoutingError("No fuel plan can cover this route with a 500 mile vehicle range.")

    path_indexes = []
    cursor: int | None = count - 1
    while cursor is not None:
        path_indexes.append(cursor)
        cursor = previous[cursor]
    path_indexes.reverse()

    stops = []
    for stop_number, (current_index, next_index) in enumerate(zip(path_indexes, path_indexes[1:], strict=False)):
        station = nodes[current_index]
        if station is None:
            continue
        leg_miles = Decimal(str(miles[next_index] - miles[current_index]))
        covered_initial_miles = initial_leg_miles[current_index] if stop_number == 0 else Decimal("0")
        charged_miles = leg_miles + covered_initial_miles
        gallons = (leg_miles / Decimal(str(mpg))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        subtotal_gallons = (charged_miles / Decimal(str(mpg))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        subtotal = (subtotal_gallons * station.price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        stops.append(
            {
                "station_id": station.id,
                "name": station.name,
                "address": station.address,
                "city": station.city,
                "state": station.state,
                "latitude": round(station.lat, 6),
                "longitude": round(station.lon, 6),
                "route_mile": round(station.route_mile, 1),
                "distance_from_route_miles": round(station.distance_from_route, 1),
                "price_per_gallon": float(station.price),
                "gallons": float(gallons),
                "initial_leg_miles_estimated": float(covered_initial_miles.quantize(Decimal("0.1"))),
                "estimated_spend": float(subtotal),
            }
        )

    return stops, costs[-1].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def build_route_plan(start_query: str, finish_query: str, client: RouteClient | None = None) -> dict[str, Any]:
    use_plan_cache = client is None
    plan_cache_key = make_cache_key("route-plan:v2", normalize_query(start_query), normalize_query(finish_query))
    if use_plan_cache:
        cached_plan = cache.get(plan_cache_key)
        if cached_plan:
            plan = copy.deepcopy(cached_plan)
            plan["performance"] = {"cache": "hit"}
            return plan

    client = client or RouteClient()
    start = client.geocode(start_query)
    finish = client.geocode(finish_query)
    route = client.route(start, finish)
    points = route_points_from_geometry(route["geometry"])
    route_miles = cumulative_miles(points)
    stations = find_corridor_stations(points, route_miles, settings.ROUTE_CORRIDOR_MILES)
    stops, total_cost = optimize_fuel_stops(
        stations,
        route["distance_miles"],
        settings.VEHICLE_RANGE_MILES,
        settings.VEHICLE_MPG,
    )
    plan = {
        "start": {"label": start.label, "latitude": start.lat, "longitude": start.lon},
        "finish": {"label": finish.label, "latitude": finish.lat, "longitude": finish.lon},
        "route": {
            "distance_miles": round(route["distance_miles"], 1),
            "duration_minutes": round(route["duration_minutes"], 1),
            "geometry": route["geometry"],
        },
        "fuel_plan": {
            "vehicle_range_miles": settings.VEHICLE_RANGE_MILES,
            "vehicle_mpg": settings.VEHICLE_MPG,
            "total_gallons": round(route["distance_miles"] / settings.VEHICLE_MPG, 2),
            "total_spend": float(total_cost),
            "stops": stops,
        },
        "assumptions": [
            "Fuel prices come from the provided CSV.",
            "Truck stop coordinates are approximated from offline city coordinates because the CSV has no latitude/longitude columns.",
            "The optimizer buys only enough fuel at each chosen stop to reach the next selected stop or destination.",
            "The route geometry is returned as GeoJSON and can be drawn directly on a map client.",
        ],
    }
    if use_plan_cache:
        cache_payload = copy.deepcopy(plan)
        cache_payload["performance"] = {"cache": "hit"}
        cache.set(plan_cache_key, cache_payload, settings.ROUTE_PLAN_CACHE_SECONDS)
        plan["performance"] = {"cache": "miss"}
    return plan
