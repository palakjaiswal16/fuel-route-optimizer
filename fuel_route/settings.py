from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "django-insecure-local-assessment-key"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "routing.apps.RoutingConfig",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "fuel_route.urls"
WSGI_APPLICATION = "fuel_route.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "fuel-route-cache",
    }
}

FUEL_PRICE_CSV = BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv"
GEOCODE_CACHE_PATH = BASE_DIR / "data" / "geocode-cache.json"
OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "fuel-route-assessment/1.0 (local demo)"
ROUTE_PLAN_CACHE_SECONDS = 60 * 60 * 24
ROUTE_CACHE_SECONDS = 60 * 60 * 24

VEHICLE_RANGE_MILES = 500
VEHICLE_MPG = 10
ROUTE_CORRIDOR_MILES = 60
