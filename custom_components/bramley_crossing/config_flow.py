"""UI configuration for the public crossing service and feed freshness."""

from typing import Any

import voluptuous as vol
from aiohttp import ClientError
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_URL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import CrossingClient, InvalidStatus, normalize_base_url
from .const import (
    CONF_STALE_TIMEOUT,
    DEFAULT_STALE_TIMEOUT,
    DOMAIN,
    MAX_STALE_TIMEOUT,
    MIN_STALE_TIMEOUT,
    NAME,
)
from .coordinator import CrossingConfigEntry


def _timeout_selector() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_STALE_TIMEOUT,
            max=MAX_STALE_TIMEOUT,
            step=1,
            unit_of_measurement="s",
            mode=NumberSelectorMode.BOX,
        )
    )


class CrossingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure one advisory device per service base URL."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: CrossingConfigEntry,
    ) -> OptionsFlow:
        """Create the options flow without assigning its config_entry."""
        return CrossingOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate the URL and feed before creating an entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                base_url = normalize_base_url(user_input[CONF_URL])
            except (ValueError, TypeError):
                errors[CONF_URL] = "invalid_url"
            else:
                self._async_abort_entries_match({CONF_URL: base_url})
                timeout = int(user_input[CONF_STALE_TIMEOUT])
                client = CrossingClient(async_get_clientsession(self.hass), base_url)
                try:
                    await client.async_get_status(timeout)
                except (ClientError, TimeoutError):
                    errors["base"] = "cannot_connect"
                except (InvalidStatus, ValueError):
                    errors["base"] = "invalid_status"
                else:
                    return self.async_create_entry(
                        title=NAME,
                        data={CONF_URL: base_url},
                        options={CONF_STALE_TIMEOUT: timeout},
                    )
        defaults = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=defaults.get(CONF_URL, "")): str,
                    vol.Required(
                        CONF_STALE_TIMEOUT,
                        default=defaults.get(CONF_STALE_TIMEOUT, DEFAULT_STALE_TIMEOUT),
                    ): _timeout_selector(),
                }
            ),
            errors=errors,
        )


class CrossingOptionsFlow(OptionsFlow):
    """Offer a friendly feed stale-timeout setting."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change feed freshness policy and reload the integration."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={CONF_STALE_TIMEOUT: int(user_input[CONF_STALE_TIMEOUT])},
            )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_STALE_TIMEOUT,
                        default=self.config_entry.options.get(
                            CONF_STALE_TIMEOUT, DEFAULT_STALE_TIMEOUT
                        ),
                    ): _timeout_selector(),
                }
            ),
        )
