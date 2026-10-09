"""Validate data mapping, freshness, and the actual HTTP client."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from aiohttp import ClientResponseError, ClientSession, ClientTimeout, web

from custom_components.bramley_crossing.api import (
    CrossingClient,
    InvalidStatus,
    normalize_base_url,
    parse_status,
)
from custom_components.bramley_crossing.const import STATES


def parse(payload, age=0, timeout=90):
    """Validate using a deterministic heartbeat-relative clock."""
    updated = datetime.fromisoformat(payload["feedStatus"]["updatedAt"])
    return parse_status(
        payload, stale_timeout=timeout, now=updated + timedelta(seconds=age)
    )


@pytest.mark.parametrize("state", STATES)
def test_mapping(status_payload, state):
    status_payload["state"] = state
    status = parse(status_payload)
    assert status.state == state
    assert status.observed_at == datetime(2026, 1, 1, 10, tzinfo=UTC)
    assert status.predicted_close_at == datetime(2026, 10, 9, 9, 5, tzinfo=UTC)
    assert status.typical_closure_seconds == 125.5
    assert status.last_message_at is None


@pytest.mark.parametrize("state", [None, "", "Unexpected", 42, [], {}])
def test_unknown_state(status_payload, state):
    status_payload["state"] = state
    assert parse(status_payload).state == "Unknown"


def test_missing_optional_values(status_payload):
    for key in ("state", "observedAt", "predictedCloseAt", "typicalClosureSeconds"):
        del status_payload[key]
    status = parse(status_payload)
    assert status.state == "Unknown"
    assert status.observed_at is None
    assert status.predicted_close_at is None
    assert status.typical_closure_seconds is None


@pytest.mark.parametrize("duration", [None, 0, 90, 90.5])
def test_nullable_predictions_and_duration(status_payload, duration):
    status_payload["predictedCloseAt"] = None
    status_payload["typicalClosureSeconds"] = duration
    status = parse(status_payload)
    assert status.predicted_close_at is None
    assert status.typical_closure_seconds == duration


@pytest.mark.parametrize(
    "duration", [True, False, -1, "90", [], float("nan"), float("inf")]
)
def test_invalid_duration(status_payload, duration):
    status_payload["typicalClosureSeconds"] = duration
    with pytest.raises(InvalidStatus, match="typicalClosureSeconds"):
        parse(status_payload)


@pytest.mark.parametrize(
    "feed",
    [
        None,
        {},
        [],
        {"connected": True},
        {"connected": True, "updatedAt": None, "lastMessageAt": None},
        {"connected": False, "updatedAt": "bad", "lastMessageAt": None},
        {"connected": "true", "updatedAt": "bad", "lastMessageAt": None},
    ],
)
def test_missing_malformed_disconnected_feed(status_payload, feed):
    status_payload["feedStatus"] = feed
    with pytest.raises(InvalidStatus):
        parse_status(status_payload, stale_timeout=90, now=datetime.now(UTC))


@pytest.mark.parametrize("field", ["observedAt", "predictedCloseAt"])
@pytest.mark.parametrize("value", ["not-a-time", "2026-10-09T10:00:00", 123])
def test_invalid_timestamp(status_payload, field, value):
    status_payload[field] = value
    with pytest.raises(InvalidStatus, match=field):
        parse(status_payload)


@pytest.mark.parametrize("field", ["updatedAt", "lastMessageAt"])
@pytest.mark.parametrize("value", ["invalid", "2026-10-09T10:00:00", 123])
def test_invalid_feed_timestamp(status_payload, field, value):
    status_payload["feedStatus"][field] = value
    with pytest.raises(InvalidStatus, match=field):
        parse_status(status_payload, stale_timeout=90, now=datetime.now(UTC))


@pytest.mark.parametrize("payload", [None, [], "invalid", 42])
def test_invalid_root(payload):
    with pytest.raises(InvalidStatus, match="JSON object"):
        parse_status(payload, stale_timeout=90, now=datetime.now(UTC))


def test_stale_boundary_and_configurable_timeout(status_payload):
    assert parse(status_payload, age=90).state == "ClosingSoon"
    with pytest.raises(InvalidStatus, match="stale"):
        parse(status_payload, age=90.001)
    assert parse(status_payload, age=120, timeout=180).state == "ClosingSoon"
    with pytest.raises(InvalidStatus, match="future"):
        parse(status_payload, age=-31)


def test_heartbeat_does_not_change_observation(status_payload):
    old = parse(status_payload)
    updated = old.feed_updated_at + timedelta(seconds=15)
    status_payload["feedStatus"]["updatedAt"] = updated.isoformat()
    status_payload["feedStatus"]["lastMessageAt"] = "2026-01-01T10:00:00Z"
    new = parse(status_payload)
    assert new.feed_updated_at != old.feed_updated_at
    assert new.observed_at == old.observed_at
    assert new.state == old.state


@pytest.mark.parametrize(
    "url,normalized",
    [
        (" https://example.org/ ", "https://example.org"),
        ("http://example.org/prefix///", "http://example.org/prefix"),
        ("http://localhost:8080", "http://localhost:8080"),
    ],
)
def test_url_normalization(url, normalized):
    assert normalize_base_url(url) == normalized


@pytest.mark.parametrize(
    "url",
    [
        "",
        "example.org",
        "ftp://example.org",
        "https://user:pass@example.org",
        "https://example.org?q=1",
        "https://example.org/#section",
        "http://example.org:70000",
        "http://example.org:invalid",
    ],
)
def test_invalid_url(url):
    with pytest.raises(ValueError):
        normalize_base_url(url)


async def test_http_mapping_and_proxy_prefix(
    aiohttp_server, status_payload, socket_enabled
):
    async def handler(request):
        assert request.path == "/prefix/api/status"
        assert "Authorization" not in request.headers
        return web.json_response(status_payload)

    app = web.Application()
    app.router.add_get("/prefix/api/status", handler)
    server = await aiohttp_server(app)
    async with ClientSession() as session:
        client = CrossingClient(session, str(server.make_url("/prefix/")))
        status = await client.async_get_status(90)
    assert status.state == "ClosingSoon"


async def test_http_failure(aiohttp_server, socket_enabled):
    async def handler(request):
        raise web.HTTPServiceUnavailable()

    app = web.Application()
    app.router.add_get("/api/status", handler)
    server = await aiohttp_server(app)
    async with ClientSession() as session:
        with pytest.raises(ClientResponseError):
            await CrossingClient(session, str(server.make_url(""))).async_get_status(90)


@pytest.mark.parametrize("failure", ["disconnected", "stale", "missing", "json"])
async def test_http_invalid_status(
    aiohttp_server, status_payload, failure, socket_enabled
):
    if failure == "disconnected":
        status_payload["feedStatus"]["connected"] = False
    elif failure == "stale":
        status_payload["feedStatus"]["updatedAt"] = (
            datetime.now(UTC) - timedelta(seconds=91)
        ).isoformat()
    elif failure == "missing":
        del status_payload["feedStatus"]

    async def handler(request):
        if failure == "json":
            return web.Response(text="{broken", content_type="application/json")
        return web.json_response(status_payload)

    app = web.Application()
    app.router.add_get("/api/status", handler)
    server = await aiohttp_server(app)
    async with ClientSession() as session:
        with pytest.raises(ValueError):
            await CrossingClient(session, str(server.make_url(""))).async_get_status(90)


async def test_request_timeout():
    session = MagicMock(spec=ClientSession)
    session.get.side_effect = TimeoutError
    with pytest.raises(TimeoutError):
        await CrossingClient(session, "https://example.org").async_get_status(90)
    session.get.assert_called_once_with(
        "https://example.org/api/status", timeout=ClientTimeout(total=10)
    )
