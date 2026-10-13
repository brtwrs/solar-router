"""A switch per consumer to take it in or out of the routing."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

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
    """Add a managed and a force switch per consumer."""
    coordinator = entry.runtime_data

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_CONSUMER:
            continue
        async_add_entities(
            [
                ManagedSwitch(coordinator, entry, subentry),
                ForceSwitch(coordinator, entry, subentry),
            ],
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


class ForceSwitch(SolarRouterConsumerEntity, SwitchEntity, RestoreEntity):
    """Run this consumer regardless of the sun, still under the phase limit.

    Unlike taking it out of the routing, the router keeps hold of it: a phase
    over its limit switches it off, and it starts again once there is room.
    Survives a restart, so a forced charge does not silently stop halfway.
    """

    _attr_translation_key = "force"

    def __init__(
        self,
        coordinator: SolarRouterCoordinator,
        entry: SolarRouterConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Set up the force switch."""
        super().__init__(coordinator, entry, subentry)
        self._attr_unique_id = f"{subentry.subentry_id}_force"

    async def async_added_to_hass(self) -> None:
        """Pick up where we were before a restart."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self.consumer_state.forced = last.state == STATE_ON

    @property
    def is_on(self) -> bool:
        """Whether this consumer runs regardless of surplus."""
        return self.consumer_state.forced

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Run it, sun or not."""
        self.consumer_state.forced = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Back to running on surplus only."""
        self.consumer_state.forced = False
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
