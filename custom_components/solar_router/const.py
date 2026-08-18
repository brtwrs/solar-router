"""Constants for Solar Router."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "solar_router"

SUBENTRY_TYPE_CONSUMER: Final = "consumer"

# --- hub configuration ---
CONF_GRID_SENSOR: Final = "grid_sensor"
CONF_GRID_EXPORT_IS_NEGATIVE: Final = "grid_export_is_negative"
CONF_RESERVE: Final = "reserve"
CONF_INTERVAL: Final = "interval"

DEFAULT_EXPORT_IS_NEGATIVE: Final = True
DEFAULT_RESERVE: Final = 0
DEFAULT_INTERVAL: Final = 30

# --- consumer configuration ---
CONF_NAME: Final = "name"
CONF_SWITCH_ENTITY: Final = "switch_entity"
CONF_NUMBER_ENTITY: Final = "number_entity"
CONF_POWER_MIN: Final = "power_min"
CONF_POWER_MAX: Final = "power_max"
CONF_PRIORITY: Final = "priority"
CONF_MIN_ON: Final = "min_on"
CONF_MIN_OFF: Final = "min_off"

DEFAULT_PRIORITY: Final = 50
DEFAULT_MIN_ON: Final = 300
DEFAULT_MIN_OFF: Final = 300

# --- attributes exposed on the hub sensor ---
ATTR_ALLOCATIONS: Final = "allocations"
ATTR_SURPLUS: Final = "surplus"
ATTR_UNUSED: Final = "unused"
