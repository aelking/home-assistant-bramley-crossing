"""Fixtures for the standalone custom integration."""

from datetime import UTC, datetime

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def enable_integration(enable_custom_integrations):
    """Allow loading the custom integration in Home Assistant."""


@pytest.fixture
def status_payload():
    """Return a healthy feed with an intentionally older observation."""
    now = datetime.now(UTC).isoformat()
    return {
        "state": "ClosingSoon",
        "observedAt": "2026-01-01T10:00:00Z",
        "predictedCloseAt": "2026-10-09T10:05:00+01:00",
        "typicalClosureSeconds": 125.5,
        "feedStatus": {
            "connected": True,
            "updatedAt": now,
            "lastMessageAt": None,
        },
    }
