"""A switch per consumer to take it in or out of the routing."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SolarRouterConfigEntry
from .const import DOMAIN, SUBENTRY_TYPE_CONSUMER
from .coordinator import SolarRouterCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarRouterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One managed switch per consumer."""
    coordinator = entry.runtime_data

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_CONSUMER:
            continue
        async_add_entities(
            [ManagedSwitch(coordinator, entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class ManagedSwitch(CoordinatorEntity[SolarRouterCoordinator], SwitchEntity):
    """Turn routing for this consumer on or off.

    Off means the router stops touching it; whatever it was doing is left
    alone. Useful when you want to run the car charger manually.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "managed"

    def __init__(self, coordinator, entry, subentry) -> None:
        super().__init__(coordinator)
        self._subentry_id = subentry.subentry_id
        self._name = subentry.title
        self._attr_unique_id = f"{subentry.subentry_id}_managed"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Solar Router",
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def is_on(self) -> bool:
        return self.coordinator.state_for(self._subentry_id, self._name).managed

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.state_for(self._subentry_id, self._name).managed = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        state = self.coordinator.state_for(self._subentry_id, self._name)
        state.managed = False
        state.allocated = 0.0
        state.reason = "not managed"
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
