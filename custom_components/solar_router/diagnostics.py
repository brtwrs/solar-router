"""Diagnostics dump for a config entry.

Entity ids are the interesting part of a bug report here, and they are not
secrets, so nothing needs redacting beyond the entry's own bookkeeping.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import SolarRouterConfigEntry
from .const import SUBENTRY_TYPE_CONSUMER


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SolarRouterConfigEntry
) -> dict[str, Any]:
    """Return everything needed to reason about a misbehaving router."""
    coordinator = entry.runtime_data
    data = coordinator.data

    return {
        "hub": {
            "data": dict(entry.data),
            "options": dict(entry.options),
            "update_interval": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "last_update_success": coordinator.last_update_success,
        },
        "consumers": [
            {
                "title": subentry.title,
                "data": dict(subentry.data),
            }
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_CONSUMER
        ],
        "last_cycle": (
            {
                "surplus": data.surplus,
                "budget": data.budget,
                "unused": data.unused,
                "settling": data.settling,
                "consumers": {
                    key: asdict(state) for key, state in data.consumers.items()
                },
            }
            if data is not None
            else None
        ),
        # What each source entity reads right now, so a report shows whether the
        # inputs or the allocation is at fault.
        "inputs": coordinator.input_snapshot(),
    }
