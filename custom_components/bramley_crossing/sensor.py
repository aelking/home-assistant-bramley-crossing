"""Expose signal-inferred advisories, never physical barrier telemetry."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import CONF_URL, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import CrossingStatus
from .const import ADVISORY, DOMAIN, INFERENCE_BASIS, NAME, STATES
from .coordinator import CrossingConfigEntry, CrossingCoordinator


@dataclass(frozen=True, kw_only=True)
class CrossingSensorDescription(SensorEntityDescription):
    """Describe how a sensor maps the validated status."""

    value_fn: Callable[[CrossingStatus], str | datetime | float | None]


SENSORS = (
    CrossingSensorDescription(
        key="state",
        translation_key="inferred_state",
        device_class=SensorDeviceClass.ENUM,
        options=list(STATES),
        value_fn=lambda data: data.state,
    ),
    CrossingSensorDescription(
        key="predicted_close_at",
        translation_key="predicted_close_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.predicted_close_at,
    ),
    CrossingSensorDescription(
        key="typical_closure_seconds",
        translation_key="typical_closure_seconds",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda data: data.typical_closure_seconds,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CrossingConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the three advisory sensors."""
    async_add_entities(
        CrossingSensor(entry.runtime_data, entry, description)
        for description in SENSORS
    )


class CrossingSensor(CoordinatorEntity[CrossingCoordinator], SensorEntity):
    """Share availability across all three signal-inferred sensors."""

    _attr_has_entity_name = True
    entity_description: CrossingSensorDescription

    def __init__(
        self,
        coordinator: CrossingCoordinator,
        entry: CrossingConfigEntry,
        description: CrossingSensorDescription,
    ) -> None:
        """Initialize a stable entity and clearly labeled advisory device."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="Bramley crossing service",
            model=INFERENCE_BASIS,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=entry.data[CONF_URL],
        )

    @property
    def native_value(self) -> str | datetime | float | None:
        """Return Unknown for unknown inference, or None for absent predictions."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Keep the original observation time distinct from feed heartbeats."""
        data = self.coordinator.data
        return {
            "inference_basis": INFERENCE_BASIS,
            "advisory": ADVISORY,
            "observed_at": data.observed_at.isoformat() if data.observed_at else None,
            "feed_updated_at": data.feed_updated_at.isoformat(),
            "last_message_at": (
                data.last_message_at.isoformat() if data.last_message_at else None
            ),
        }
