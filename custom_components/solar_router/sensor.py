"""Sensors: one overview for the hub, one allocation figure per consumer."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SolarRouterConfigEntry
from .const import ATTR_ALLOCATIONS, ATTR_SURPLUS, ATTR_UNUSED, DOMAIN, SUBENTRY_TYPE_CONSUMER
from .coordinator import SolarRouterCoordinator


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


class SurplusSensor(CoordinatorEntity[SolarRouterCoordinator], SensorEntity):
    """How much surplus is left after everyone has been served."""

    _attr_has_entity_name = True
    _attr_translation_key = "unused_surplus"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(
        self, coordinator: SolarRouterCoordinator, entry: SolarRouterConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_unused"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Solar Router",
            manufacturer="Solar Router",
            entry_type="service",
        )

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return round(self.coordinator.data.unused)

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            ATTR_SURPLUS: round(data.surplus),
            "budget": round(data.budget),
            ATTR_UNUSED: round(data.unused),
            "settling": data.settling,
            ATTR_ALLOCATIONS: {
                s.name: {"watt": round(s.allocated), "state": s.reason}
                for s in data.consumers.values()
            },
        }


class ConsumerPowerSensor(CoordinatorEntity[SolarRouterCoordinator], SensorEntity):
    """Power currently routed to one consumer."""

    _attr_has_entity_name = True
    _attr_translation_key = "allocated"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coordinator, entry, subentry) -> None:
        super().__init__(coordinator)
        self._subentry_id = subentry.subentry_id
        self._attr_unique_id = f"{subentry.subentry_id}_allocated"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Solar Router",
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if data is None:
            return None
        state = data.consumers.get(self._subentry_id)
        return round(state.allocated) if state else 0

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if data is None:
            return {}
        state = data.consumers.get(self._subentry_id)
        return {"state": state.reason} if state else {}
