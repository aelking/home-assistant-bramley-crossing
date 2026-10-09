"""Constants for the Bramley crossing advisory integration."""

from datetime import timedelta

DOMAIN = "bramley_crossing"
NAME = "Bramley Crossing (signal-inferred advisory)"
CONF_STALE_TIMEOUT = "stale_timeout"
DEFAULT_STALE_TIMEOUT = 90
MIN_STALE_TIMEOUT = 30
MAX_STALE_TIMEOUT = 3600
UPDATE_INTERVAL = timedelta(seconds=30)
REQUEST_TIMEOUT = 10
STATES = ("Unknown", "Open", "ClosingSoon", "Closed")
INFERENCE_BASIS = "Protecting-signal aspects, not physical barrier telemetry"
ADVISORY = (
    "Always obey physical crossing lights and barriers. "
    "Advisory only; not for safety-critical control."
)
