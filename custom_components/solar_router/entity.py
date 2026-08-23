"""Shared entity base classes.

Both platforms hang off the same coordinator and describe the same two kinds of
device — the hub, and one device per consumer — so the device wiring lives here
rather than being repeated per platform.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import ConsumerState, SolarRouterCoordinator


class SolarRouterEntity(CoordinatorEntity[SolarRouterCoordinator]):
    """Anything belonging to the hub device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SolarRouterCoordinator, entry: ConfigEntry) -> None:
        """Attach to the hub device."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Solar Router",
            manufacturer=MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
        )


class SolarRouterConsumerEntity(CoordinatorEntity[SolarRouterCoordinator]):
    """Anything belonging to one consumer device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SolarRouterCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """Attach to the consumer device, hung under the hub."""
        super().__init__(coordinator)
        self._subentry_id = subentry.subentry_id
        self._consumer_name = subentry.title
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer=MANUFACTURER,
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def consumer_state(self) -> ConsumerState:
        """The bookkeeping for this consumer."""
        return self.coordinator.state_for(self._subentry_id, self._consumer_name)
