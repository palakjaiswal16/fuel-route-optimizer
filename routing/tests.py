from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase

from .services import FuelStation, Location, geocode_city_state_locally, optimize_fuel_stops


class FuelOptimizerTests(SimpleTestCase):
    def test_optimizer_chooses_lowest_cost_reachable_path(self):
        stations = [
            FuelStation("1", "Expensive Start", "", "A", "TX", Decimal("4.000"), 0, 0, 0, 0),
            FuelStation("2", "Cheap Middle", "", "B", "TX", Decimal("2.000"), 0, 0, 300, 0),
            FuelStation("3", "Costly Detour", "", "C", "TX", Decimal("5.000"), 0, 0, 450, 0),
        ]

        stops, total = optimize_fuel_stops(stations, total_miles=700, max_range_miles=500, mpg=10)

        self.assertEqual([stop["station_id"] for stop in stops], ["2"])
        self.assertEqual(total, Decimal("140.00"))
        self.assertEqual(stops[0]["gallons"], 40.0)
        self.assertEqual(stops[0]["initial_leg_miles_estimated"], 300.0)

    def test_optimizer_reports_unreachable_route(self):
        stations = [
            FuelStation("1", "Start", "", "A", "TX", Decimal("4.000"), 0, 0, 0, 0),
            FuelStation("2", "Too Far", "", "B", "TX", Decimal("2.000"), 0, 0, 700, 0),
        ]

        with self.assertRaisesMessage(Exception, "No fuel plan can cover this route"):
            optimize_fuel_stops(stations, total_miles=1200, max_range_miles=500, mpg=10)

    def test_city_state_geocoding_uses_offline_index(self):
        location = geocode_city_state_locally("Dallas, TX")

        self.assertIsNotNone(location)
        self.assertAlmostEqual(location.latitude if hasattr(location, "latitude") else location.lat, 32.78, places=1)


class RoutePlanViewTests(TestCase):
    def test_requires_post(self):
        response = Client().get("/api/route-plan/")

        self.assertEqual(response.status_code, 405)

    def test_validates_required_locations(self):
        response = Client().post(
            "/api/route-plan/",
            data=json.dumps({"start": "Dallas, TX"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    @patch("routing.views.build_route_plan")
    def test_returns_route_plan(self, build_route_plan):
        build_route_plan.return_value = {
            "start": {"label": "Dallas, TX", "latitude": 32.7767, "longitude": -96.797},
            "finish": {"label": "Austin, TX", "latitude": 30.2672, "longitude": -97.7431},
            "route": {"distance_miles": 195.0, "duration_minutes": 180.0, "geometry": {"type": "LineString", "coordinates": []}},
            "fuel_plan": {"vehicle_range_miles": 500, "vehicle_mpg": 10, "total_gallons": 19.5, "total_spend": 62.4, "stops": []},
        }

        response = Client().post(
            "/api/route-plan/",
            data=json.dumps({"start": "Dallas, TX", "finish": "Austin, TX"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fuel_plan"]["total_spend"], 62.4)
        self.assertIn("map_preview_url", response.json())
        self.assertIn("response_time_ms", response.json()["performance"])
        build_route_plan.assert_called_once_with("Dallas, TX", "Austin, TX")

    def test_map_preview_page_loads(self):
        response = Client().get("/map/?start=Dallas%2C+TX&finish=Austin%2C+TX")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fuel Route Map")


class FakeClient:
    def geocode(self, query):
        locations = {
            "Dallas, TX": Location("Dallas, TX", 32.7767, -96.7970),
            "Austin, TX": Location("Austin, TX", 30.2672, -97.7431),
        }
        return locations[query]

    def route(self, start, finish):
        return {
            "distance_miles": 200,
            "duration_minutes": 180,
            "geometry": {
                "type": "LineString",
                "coordinates": [[-96.7970, 32.7767], [-97.7431, 30.2672]],
            },
        }


class RoutePlanServiceTests(SimpleTestCase):
    @patch("routing.services.find_corridor_stations")
    def test_build_route_plan_with_mocked_services(self, find_corridor_stations):
        from .services import build_route_plan

        find_corridor_stations.return_value = [
            FuelStation("1", "Start Fuel", "", "Dallas", "TX", Decimal("3.000"), 32.77, -96.79, 0, 1),
            FuelStation("2", "Mid Fuel", "", "Waco", "TX", Decimal("2.500"), 31.55, -97.14, 100, 2),
        ]

        plan = build_route_plan("Dallas, TX", "Austin, TX", client=FakeClient())

        self.assertEqual(plan["route"]["distance_miles"], 200)
        self.assertEqual(plan["fuel_plan"]["total_spend"], 50.0)
        self.assertEqual(plan["fuel_plan"]["stops"][0]["station_id"], "2")
