"""Exercise real HA setup, entity state, failure recovery, and reload."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import ClientConnectionError, web
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_URL, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.bramley_crossing.api import InvalidStatus, parse_status
from custom_components.bramley_crossing.const import (
    ADVISORY,
    CONF_STALE_TIMEOUT,
    DOMAIN,
    INFERENCE_BASIS,
)

CLIENT = "custom_components.bramley_crossing.api.CrossingClient.async_get_status"


async def setup(hass, payload):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: "https://example.org"},
        options={CONF_STALE_TIMEOUT: 90},
    )
    entry.add_to_hass(hass)
    data = parse_status(payload, stale_timeout=90, now=datetime.now(UTC))
    with patch(CLIENT, return_value=data):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    entities = {
        key: registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
        for key in ("state", "predicted_close_at", "typical_closure_seconds")
    }
    assert all(entities.values())
    return entry, entities, data


async def test_sensor_mapping_and_device(hass, status_payload):
    entry, entities, _ = await setup(hass, status_payload)
    state = hass.states.get(entities["state"])
    prediction = hass.states.get(entities["predicted_close_at"])
    duration = hass.states.get(entities["typical_closure_seconds"])
    assert state.state == "ClosingSoon"
    assert state.attributes["device_class"] == "enum"
    assert state.attributes["options"] == ["Unknown", "Open", "ClosingSoon", "Closed"]
    assert state.attributes["observed_at"] == "2026-01-01T10:00:00+00:00"
    assert state.attributes["inference_basis"] == INFERENCE_BASIS
    assert state.attributes["advisory"] == ADVISORY
    assert "protecting signals" in state.attributes["friendly_name"]
    assert prediction.state == "2026-10-09T09:05:00+00:00"
    assert prediction.attributes["device_class"] == "timestamp"
    assert float(duration.state) == 125.5
    assert duration.attributes["unit_of_measurement"] == "s"
    assert duration.attributes["device_class"] == "duration"
    entity = er.async_get(hass).async_get(entities["state"])
    device = dr.async_get(hass).async_get(entity.device_id)
    assert device.model == INFERENCE_BASIS
    assert "signal-inferred advisory" in device.name


async def test_unknown_values(hass, status_payload):
    status_payload["state"] = "Unknown"
    status_payload["predictedCloseAt"] = None
    status_payload["typicalClosureSeconds"] = None
    _, entities, _ = await setup(hass, status_payload)
    assert hass.states.get(entities["state"]).state == "Unknown"
    assert hass.states.get(entities["predicted_close_at"]).state == STATE_UNKNOWN
    assert hass.states.get(entities["typical_closure_seconds"]).state == STATE_UNKNOWN


@pytest.mark.parametrize(
    "error",
    [
        ClientConnectionError("HTTP failure"),
        TimeoutError(),
        ValueError("Invalid JSON"),
        InvalidStatus("disconnected"),
        InvalidStatus("stale"),
        InvalidStatus("malformed feedStatus"),
    ],
)
async def test_unavailable_and_recovery(hass, status_payload, error):
    entry, entities, data = await setup(hass, status_payload)
    with patch(CLIENT, side_effect=error):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    assert all(
        hass.states.get(entity).state == STATE_UNAVAILABLE
        for entity in entities.values()
    )
    with patch(CLIENT, return_value=data):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get(entities["state"]).state == "ClosingSoon"
    assert all(
        hass.states.get(entity).state != STATE_UNAVAILABLE
        for entity in entities.values()
    )


async def test_initial_failure_retries(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_URL: "https://example.org"})
    entry.add_to_hass(hass)
    with patch(CLIENT, side_effect=TimeoutError()):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state.value == "setup_retry"


async def test_poll_heartbeat_and_unload(hass, status_payload, freezer):
    entry, entities, old = await setup(hass, status_payload)
    freezer.tick(30)
    status_payload["feedStatus"]["updatedAt"] = datetime.now(UTC).isoformat()
    data = parse_status(status_payload, stale_timeout=90, now=datetime.now(UTC))
    with patch(CLIENT, return_value=data) as client:
        async_fire_time_changed(hass, datetime.now(UTC) + timedelta(seconds=1))
        await hass.async_block_till_done()
    client.assert_awaited_once_with(90)
    assert entry.runtime_data.update_interval == timedelta(seconds=30)
    assert entry.runtime_data.data.observed_at == old.observed_at
    assert entry.runtime_data.data.feed_updated_at != old.feed_updated_at
    assert hass.states.get(entities["state"]).attributes["observed_at"] == (
        old.observed_at.isoformat()
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    with patch(CLIENT, new_callable=AsyncMock) as client:
        freezer.tick(60)
        async_fire_time_changed(hass, datetime.now(UTC))
        await hass.async_block_till_done()
    client.assert_not_awaited()


async def test_options_reload(hass, status_payload):
    entry, _, data = await setup(hass, status_payload)
    old = entry.runtime_data
    with patch(CLIENT, return_value=data) as client:
        hass.config_entries.async_update_entry(entry, options={CONF_STALE_TIMEOUT: 180})
        await hass.async_block_till_done()
    assert entry.runtime_data is not old
    assert entry.runtime_data.stale_timeout == 180
    client.assert_awaited_once_with(180)


async def test_live_status_endpoint(
    hass, aiohttp_server, socket_enabled, status_payload
):
    """Follow actual HTTP through config flow, coordinator, and entity states."""
    http_status = 200
    requests = 0

    async def handler(request):
        nonlocal requests
        requests += 1
        return web.json_response(status_payload, status=http_status)

    app = web.Application()
    app.router.add_get("/api/status", handler)
    server = await aiohttp_server(app)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            CONF_URL: str(server.make_url("")),
            CONF_STALE_TIMEOUT: 90,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.state.value == "loaded"
    assert requests == 2
    registry = er.async_get(hass)
    entities = {
        key: registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
        for key in ("state", "predicted_close_at", "typical_closure_seconds")
    }
    original_observation = hass.states.get(entities["state"]).attributes["observed_at"]
    assert hass.states.get(entities["state"]).state == "ClosingSoon"

    status_payload["feedStatus"]["updatedAt"] = (
        datetime.now(UTC) - timedelta(seconds=91)
    ).isoformat()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert all(
        hass.states.get(entity).state == STATE_UNAVAILABLE
        for entity in entities.values()
    )

    status_payload["feedStatus"]["updatedAt"] = datetime.now(UTC).isoformat()
    status_payload["state"] = "Unknown"
    status_payload["predictedCloseAt"] = None
    status_payload["typicalClosureSeconds"] = None
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entities["state"]).state == "Unknown"
    assert hass.states.get(entities["predicted_close_at"]).state == STATE_UNKNOWN
    assert hass.states.get(entities["typical_closure_seconds"]).state == STATE_UNKNOWN
    assert hass.states.get(entities["state"]).attributes["observed_at"] == (
        original_observation
    )

    status_payload["feedStatus"]["connected"] = False
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert all(
        hass.states.get(entity).state == STATE_UNAVAILABLE
        for entity in entities.values()
    )

    status_payload["feedStatus"]["connected"] = True
    http_status = 503
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert all(
        hass.states.get(entity).state == STATE_UNAVAILABLE
        for entity in entities.values()
    )
    http_status = 200
    status_payload["state"] = "Open"
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entities["state"]).state == "Open"
    assert all(
        hass.states.get(entity).state != STATE_UNAVAILABLE
        for entity in entities.values()
    )
