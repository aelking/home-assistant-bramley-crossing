"""Fetch and validate the crossing service's public status contract."""

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite

from aiohttp import ClientSession, ClientTimeout
from yarl import URL

from .const import REQUEST_TIMEOUT, STATES, UPDATE_INTERVAL


class InvalidStatus(ValueError):
    """The service returned an invalid, disconnected, or stale status."""


def normalize_base_url(value: str) -> str:
    """Normalize a service URL, retaining any reverse-proxy path prefix."""
    url = URL(value.strip())
    if (
        url.scheme not in ("http", "https")
        or not url.host
        or url.user is not None
        or url.password is not None
        or url.query_string
        or url.fragment
    ):
        raise ValueError(
            "Use an HTTP(S) base URL without credentials, query or fragment"
        )
    # Accessing port validates malformed/out-of-range ports as well.
    _ = url.port
    return str(url).rstrip("/")


def _timestamp(value: object, field: str) -> datetime | None:
    """Parse an optional ISO timestamp, requiring an explicit time zone."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidStatus(f"{field} must be an ISO timestamp or null")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as err:
        raise InvalidStatus(f"{field} is not an ISO timestamp") from err
    if result.tzinfo is None:
        raise InvalidStatus(f"{field} must include a time zone")
    return result.astimezone(UTC)


@dataclass(frozen=True)
class CrossingStatus:
    """A validated observation and independently refreshed feed heartbeat."""

    state: str
    observed_at: datetime | None
    predicted_close_at: datetime | None
    typical_closure_seconds: float | None
    feed_updated_at: datetime
    last_message_at: datetime | None


def parse_status(
    payload: object, *, stale_timeout: int, now: datetime
) -> CrossingStatus:
    """Validate feed health before mapping the advisory values."""
    if not isinstance(payload, dict):
        raise InvalidStatus("Status must be a JSON object")
    feed = payload.get("feedStatus")
    if not isinstance(feed, dict) or not {
        "connected",
        "updatedAt",
        "lastMessageAt",
    }.issubset(feed):
        raise InvalidStatus("feedStatus is missing or malformed")
    if feed["connected"] is not True:
        raise InvalidStatus("The protecting-signal feed is disconnected")
    updated_at = _timestamp(feed["updatedAt"], "feedStatus.updatedAt")
    if updated_at is None:
        raise InvalidStatus("feedStatus.updatedAt is required")
    age = (now - updated_at).total_seconds()
    if age > stale_timeout:
        raise InvalidStatus("The protecting-signal feed heartbeat is stale")
    if age < -UPDATE_INTERVAL.total_seconds():
        raise InvalidStatus("The feed heartbeat is in the future; check service clocks")
    duration = payload.get("typicalClosureSeconds")
    if duration is not None and (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not isfinite(duration)
        or duration < 0
    ):
        raise InvalidStatus("typicalClosureSeconds must be finite and non-negative")
    state = payload.get("state")
    return CrossingStatus(
        state=state if isinstance(state, str) and state in STATES else "Unknown",
        observed_at=_timestamp(payload.get("observedAt"), "observedAt"),
        predicted_close_at=_timestamp(
            payload.get("predictedCloseAt"), "predictedCloseAt"
        ),
        typical_closure_seconds=float(duration) if duration is not None else None,
        feed_updated_at=updated_at,
        last_message_at=_timestamp(feed["lastMessageAt"], "feedStatus.lastMessageAt"),
    )


class CrossingClient:
    """Use Home Assistant's shared aiohttp session; no credentials required."""

    def __init__(self, session: ClientSession, base_url: str) -> None:
        """Initialize the public status client."""
        self._session = session
        self._status_url = f"{normalize_base_url(base_url)}/api/status"

    async def async_get_status(self, stale_timeout: int) -> CrossingStatus:
        """Fetch one status; propagate transport and validation failures."""
        async with self._session.get(
            self._status_url, timeout=ClientTimeout(total=REQUEST_TIMEOUT)
        ) as response:
            response.raise_for_status()
            payload = await response.json()
        return parse_status(payload, stale_timeout=stale_timeout, now=datetime.now(UTC))
