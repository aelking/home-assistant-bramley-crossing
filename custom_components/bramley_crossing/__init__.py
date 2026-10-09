"""Bramley crossing advisories inferred from protecting-signal aspects."""

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import CrossingConfigEntry, CrossingCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: CrossingConfigEntry) -> bool:
    """Set up the coordinator and advisory sensors."""
    coordinator = CrossingCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CrossingConfigEntry) -> bool:
    """Unload sensors and stop coordinator polling."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_update_options(hass: HomeAssistant, entry: CrossingConfigEntry) -> None:
    """Reload when the user changes the stale timeout."""
    await hass.config_entries.async_reload(entry.entry_id)
