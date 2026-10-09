"""Poll the public status endpoint and expose failures as unavailable."""

import logging

from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CrossingClient, CrossingStatus, InvalidStatus
from .const import CONF_STALE_TIMEOUT, DEFAULT_STALE_TIMEOUT, NAME, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class CrossingCoordinator(DataUpdateCoordinator[CrossingStatus]):
    """Keep feed health separate from the last crossing observation."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the shared polling coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=NAME,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = CrossingClient(
            async_get_clientsession(hass), entry.data[CONF_URL]
        )
        self.stale_timeout = entry.options.get(
            CONF_STALE_TIMEOUT,
            entry.data.get(CONF_STALE_TIMEOUT, DEFAULT_STALE_TIMEOUT),
        )

    async def _async_update_data(self) -> CrossingStatus:
        """Refresh data or mark all coordinator entities unavailable."""
        try:
            return await self.client.async_get_status(self.stale_timeout)
        except (ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Cannot fetch crossing status: {err}") from err
        except (InvalidStatus, ValueError) as err:
            raise UpdateFailed(f"Invalid crossing status: {err}") from err


type CrossingConfigEntry = ConfigEntry[CrossingCoordinator]
