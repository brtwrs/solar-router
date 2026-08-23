"""A switch per consumer to take it in or out of the routing."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SolarRouterConfigEntry
from .const import REASON_NOT_MANAGED, SUBENTRY_TYPE_CONSUMER
from .coordinator import SolarRouterCoordinator
from .entity import SolarRouterConsumerEntity

# State lives in the coordinator; flipping a switch touches no external device.
PARALLEL_UPDATES = 0


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


class ManagedSwitch(SolarRouterConsumerEntity, SwitchEntity):
    """Turn routing for this consumer on or off.

    Off means the router stops touching it; whatever it was doing is left
    alone. Useful when you want to run the car charger manually.
    """

    _attr_translation_key = "managed"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: SolarRouterCoordinator,
        entry: SolarRouterConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Set up the managed switch."""
        super().__init__(coordinator, entry, subentry)
        self._attr_unique_id = f"{subentry.subentry_id}_managed"

    @property
    def is_on(self) -> bool:
        """Whether the router is allowed to drive this consumer."""
        return self.consumer_state.managed

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Hand the consumer back to the router."""
        self.consumer_state.managed = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Take the consumer out of the routing and leave it as it is."""
        state = self.consumer_state
        state.managed = False
        state.allocated = 0.0
        state.reason = REASON_NOT_MANAGED
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
