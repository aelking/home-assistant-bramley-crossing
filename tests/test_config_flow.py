"""Test UI setup, normalization, duplicate detection, and options."""

from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import ClientConnectionError
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_URL
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bramley_crossing.api import InvalidStatus
from custom_components.bramley_crossing.const import CONF_STALE_TIMEOUT, DOMAIN

CLIENT = (
    "custom_components.bramley_crossing.config_flow.CrossingClient.async_get_status"
)


async def test_form_defaults(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}
    validated = result["data_schema"]({CONF_URL: "http://localhost"})
    assert validated[CONF_STALE_TIMEOUT] == 90


async def test_setup_and_duplicate(hass):
    with (
        patch(CLIENT, new_callable=AsyncMock) as client,
        patch(
            "custom_components.bramley_crossing.async_setup_entry",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={CONF_URL: " https://example.org/ ", CONF_STALE_TIMEOUT: 120},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_URL: "https://example.org"}
    assert result["options"] == {CONF_STALE_TIMEOUT: 120}
    client.assert_awaited_once_with(120)
    with patch(CLIENT, new_callable=AsyncMock) as client:
        duplicate = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={CONF_URL: "https://example.org///", CONF_STALE_TIMEOUT: 90},
        )
    assert duplicate["type"] is FlowResultType.ABORT
    assert duplicate["reason"] == "already_configured"
    client.assert_not_awaited()


@pytest.mark.parametrize(
    "error,expected",
    [
        (ClientConnectionError("offline"), "cannot_connect"),
        (TimeoutError(), "cannot_connect"),
        (InvalidStatus("disconnected"), "invalid_status"),
        (ValueError("bad JSON"), "invalid_status"),
    ],
)
async def test_service_errors(hass, error, expected):
    with patch(CLIENT, side_effect=error):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={CONF_URL: "https://example.org", CONF_STALE_TIMEOUT: 90},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_invalid_url_and_retry(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_URL: "ftp://example.org", CONF_STALE_TIMEOUT: 90},
    )
    assert result["errors"] == {CONF_URL: "invalid_url"}
    with (
        patch(CLIENT, new_callable=AsyncMock),
        patch(
            "custom_components.bramley_crossing.async_setup_entry",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_URL: "https://example.org", CONF_STALE_TIMEOUT: 90},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_options(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: "https://example.org"},
        options={CONF_STALE_TIMEOUT: 120},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["data_schema"]({})[CONF_STALE_TIMEOUT] == 120
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_STALE_TIMEOUT: 180}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_STALE_TIMEOUT: 180}


@pytest.mark.parametrize("stale_timeout", [0, 29, 3601])
async def test_timeout_selector_range(hass, stale_timeout):
    import voluptuous as vol

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    with pytest.raises(vol.Invalid):
        result["data_schema"](
            {CONF_URL: "https://example.org", CONF_STALE_TIMEOUT: stale_timeout}
        )
