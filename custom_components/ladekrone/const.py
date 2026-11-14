"""Konstanten für Ladekrone."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ladekrone"

DEFAULT_NAME: Final = "Ladekrone"
DEFAULT_DATA_URL: Final = "https://uekala.github.io/ladekrone/v1"
DEFAULT_RADIUS_M: Final = 10_000
MAX_RADIUS_M: Final = 50_000

CONF_LOCATION: Final = "location"
CONF_MIN_POWER: Final = "min_power"
CONF_CURRENT: Final = "current_type"
CONF_CONNECTOR: Final = "connector"
CONF_OPERATORS: Final = "operators"
CONF_DATA_URL: Final = "data_url"
CONF_LOCATION_ENTITY: Final = "location_entity"
CONF_OPERATORS_ENTITY: Final = "operators_entity"
CONF_TARIFF: Final = "tariff"
CONF_CHARGE_KWH: Final = "charge_kwh"
CONF_PRICE_LIMIT: Final = "price_limit"

MIN_POWER_OPTIONS: Final = ["0", "22", "50", "150"]
CURRENT_OPTIONS: Final = ["any", "ac", "dc"]
CONNECTOR_OPTIONS: Final = ["any", "ccs", "type2", "chademo"]
TARIFF_OPTIONS: Final = ["adhoc", "contract", "subscription"]

UPDATE_INTERVAL: Final = timedelta(minutes=5)
# Betreiber melden einen Tarif meist nur neu, wenn er sich ändert. Der Zeitstempel
# ist also die letzte Änderung, nicht der letzte Abruf; erst nach 30 Tagen gilt
# ein Preis als alt.
PRICE_STALE_AFTER: Final = timedelta(days=30)
# Stündlich nachsehen; dank ETag kostet das ohne neue Daten nur eine kurze Anfrage je Datei.
FETCH_INTERVAL: Final = timedelta(hours=1)
REQUEST_TIMEOUT: Final = 30
TOP_OFFERS: Final = 5
SUPPORTED_FORMAT: Final = 1
MOVE_THRESHOLD_KM: Final = 0.5
MAX_CACHED_TILES: Final = 40
LOCATION_DOMAINS: Final = ["device_tracker", "person", "zone"]
