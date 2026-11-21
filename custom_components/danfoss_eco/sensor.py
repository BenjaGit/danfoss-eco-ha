"""Diagnostic sensors: battery, room temperature, RSSI, last poll."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from . import DanfossEcoConfigEntry
from .ble import connectable_scanners, scanner_signals
from .coordinator import EtrvCoordinator, EtrvState
from .entity import EtrvEntity


@dataclass(frozen=True, kw_only=True)
class EtrvSensorDescription(SensorEntityDescription):
    value_fn: Callable[[EtrvState], object]


# How often the per-scanner signal is sampled. The recorder stores a row per
# changed reading, so this sets the history's resolution and its size.
SIGNAL_INTERVAL = timedelta(seconds=60)

SENSORS: tuple[EtrvSensorDescription, ...] = (
    EtrvSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.battery,
    ),
    EtrvSensorDescription(
        key="room_temperature",
        translation_key="room_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.temperature.room,
    ),
    EtrvSensorDescription(
        key="rssi",
        translation_key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=True,
        value_fn=lambda s: s.rssi,
    ),
    EtrvSensorDescription(
        key="last_poll",
        translation_key="last_poll",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.last_poll,
    ),
    EtrvSensorDescription(
        key="schedule",
        translation_key="schedule",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: (
            "programmed" if s.schedule and any(s.schedule.days) else "not set"
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DanfossEcoConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(EtrvSensor(coordinator, d) for d in SENSORS),
            EtrvPendingSensor(coordinator),
            EtrvProxySensor(coordinator),
        ]
    )

    # One signal sensor per scanner. Scanners come and go (a proxy is added,
    # an adapter is switched off), so new ones are picked up as they appear.
    signal_sensors: dict[str, EtrvScannerSignalSensor] = {}

    @callback
    def refresh_signals(_now=None) -> None:
        new = [
            EtrvScannerSignalSensor(coordinator, source, name)
            for source, name in connectable_scanners(hass).items()
            if source not in signal_sensors
        ]
        for sensor in signal_sensors.values():
            if sensor.hass is not None:
                sensor.async_write_ha_state()
        if new:
            signal_sensors.update({sensor.source: sensor for sensor in new})
            async_add_entities(new)

    refresh_signals()
    entry.async_on_unload(
        async_track_time_interval(hass, refresh_signals, SIGNAL_INTERVAL)
    )


class EtrvSensor(EtrvEntity, SensorEntity):
    entity_description: EtrvSensorDescription

    def __init__(
        self, coordinator: EtrvCoordinator, description: EtrvSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):  # noqa: ANN201
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict | None:
        data = self.coordinator.data
        if data is None:
            return None
        if self.entity_description.key == "rssi":
            return {"source": data.source}
        if self.entity_description.key == "schedule" and data.schedule:
            return data.schedule.as_attributes()
        return None


class EtrvPendingSensor(EtrvEntity, SensorEntity):
    """How many changes are waiting for the thermostat to come back in range."""

    _attr_translation_key = "pending_writes"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _always_available = True

    def __init__(self, coordinator: EtrvCoordinator) -> None:
        super().__init__(coordinator, "pending_writes")

    @property
    def native_value(self) -> int:
        return self.coordinator.pending.count

    @property
    def extra_state_attributes(self) -> dict:
        pending = self.coordinator.pending
        return {"queued_since": pending.queued_at, "changes": pending.describe()}


class EtrvProxySensor(EtrvEntity, SensorEntity):
    """The Bluetooth proxy this thermostat is assigned to right now."""

    _attr_translation_key = "proxy"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _always_available = True

    def __init__(self, coordinator: EtrvCoordinator) -> None:
        super().__init__(coordinator, "proxy")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.proxy_attributes["assigned_proxy"]

    @property
    def extra_state_attributes(self) -> dict:
        attributes = self.coordinator.proxy_attributes
        return {
            "assigned_by": attributes["assigned_by"],
            "last_proxy": attributes["proxy"],
            "last_choice": attributes["proxy_choice"],
        }


class EtrvScannerSignalSensor(EtrvEntity, SensorEntity):
    """How strongly one scanner hears this thermostat's advertisements.

    Unknown while the scanner has not heard the thermostat for two minutes,
    so the history also shows how much of the time it was heard at all.
    """

    _attr_translation_key = "scanner_signal"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _always_available = True

    def __init__(self, coordinator: EtrvCoordinator, source: str, name: str) -> None:
        super().__init__(coordinator, f"signal_{source.replace(':', '').lower()}")
        self.source = source
        # Home Assistant names a proxy "bt-proxy-1 (B8:27:EB:..)"; the address
        # would only make the entity id long.
        self._attr_translation_placeholders = {"scanner": name.split(" (")[0]}
        self._attr_extra_state_attributes = {"scanner": source}

    @property
    def native_value(self) -> int | None:
        return scanner_signals(self.hass, self.coordinator.address).get(self.source)
