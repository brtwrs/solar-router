"""Sensors: one overview for the hub, one allocation figure per consumer."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SolarRouterConfigEntry
from .const import ATTR_ALLOCATIONS, ATTR_SURPLUS, ATTR_UNUSED, SUBENTRY_TYPE_CONSUMER
from .coordinator import SolarRouterCoordinator
from .entity import SolarRouterConsumerEntity, SolarRouterEntity

# Everything comes from one coordinator poll; there is nothing to serialise.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarRouterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the hub sensor plus one sensor per consumer."""
    coordinator = entry.runtime_data

    async_add_entities([SurplusSensor(coordinator, entry)])

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_CONSUMER:
            continue
        async_add_entities(
            [ConsumerPowerSensor(coordinator, entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class SurplusSensor(SolarRouterEntity, SensorEntity):
    """How much surplus is left after everyone has been served."""

    _attr_translation_key = "unused_surplus"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(
        self, coordinator: SolarRouterCoordinator, entry: SolarRouterConfigEntry
    ) -> None:
        """Set up the hub sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_unused"

    @property
    def native_value(self) -> float | None:
        """Surplus that nobody claimed, in watts."""
        if (data := self.coordinator.data) is None:
            return None
        return round(data.unused)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The whole picture of one cycle, for debugging and templates."""
        if (data := self.coordinator.data) is None:
            return {}
        return {
            ATTR_SURPLUS: round(data.surplus),
            "budget": round(data.budget),
            ATTR_UNUSED: round(data.unused),
            "settling": data.settling,
            ATTR_ALLOCATIONS: {
                state.name: {"watt": round(state.allocated), "state": state.reason}
                for state in data.consumers.values()
            },
        }


class ConsumerPowerSensor(SolarRouterConsumerEntity, SensorEntity):
    """Power currently routed to one consumer."""

    _attr_translation_key = "allocated"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(
        self,
        coordinator: SolarRouterCoordinator,
        entry: SolarRouterConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Set up the per-consumer sensor."""
        super().__init__(coordinator, entry, subentry)
        self._attr_unique_id = f"{subentry.subentry_id}_allocated"

    @property
    def native_value(self) -> float | None:
        """Watts routed to this consumer."""
        if (data := self.coordinator.data) is None:
            return None
        if (state := data.consumers.get(self._subentry_id)) is None:
            return 0
        return round(state.allocated)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Why the allocator landed on this figure."""
        if (data := self.coordinator.data) is None:
            return {}
        if (state := data.consumers.get(self._subentry_id)) is None:
            return {}
        return {"state": state.reason}
