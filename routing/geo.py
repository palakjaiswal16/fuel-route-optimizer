from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    r_lat1 = math.radians(lat1)
    r_lat2 = math.radians(lat2)
    h = (
        math.sin(d_lat / 2) ** 2
        + math.cos(r_lat1) * math.cos(r_lat2) * math.sin(d_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def cumulative_miles(points: list[tuple[float, float]]) -> list[float]:
    distances = [0.0]
    for index in range(1, len(points)):
        distances.append(distances[-1] + haversine_miles(points[index - 1], points[index]))
    return distances


def nearest_route_position(
    point: tuple[float, float],
    route_points: list[tuple[float, float]],
    route_miles: list[float],
) -> tuple[float, float]:
    nearest_index = 0
    nearest_distance = float("inf")
    for index, route_point in enumerate(route_points):
        distance = haversine_miles(point, route_point)
        if distance < nearest_distance:
            nearest_distance = distance
            nearest_index = index
    return nearest_distance, route_miles[nearest_index]


def sample_route_points(
    route_points: list[tuple[float, float]],
    route_miles: list[float],
    every_miles: float = 20.0,
) -> Iterable[tuple[tuple[float, float], float]]:
    if not route_points:
        return []
    sampled = [(route_points[0], route_miles[0])]
    next_marker = every_miles
    for point, miles in zip(route_points, route_miles, strict=False):
        if miles >= next_marker:
            sampled.append((point, miles))
            next_marker += every_miles
    if sampled[-1][0] != route_points[-1]:
        sampled.append((route_points[-1], route_miles[-1]))
    return sampled


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
