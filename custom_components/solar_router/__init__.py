"""Solar Router: spend your own solar power instead of exporting it."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import SolarRouterCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]

type SolarRouterConfigEntry = ConfigEntry[SolarRouterCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: SolarRouterConfigEntry) -> bool:
    """Set up the router."""
    coordinator = SolarRouterCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Adding, editing or removing a consumer changes the entities we expose,
    # so reload rather than try to patch things up in place.
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SolarRouterConfigEntry) -> bool:
    """Tear down."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: SolarRouterConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
