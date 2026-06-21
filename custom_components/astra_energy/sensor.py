"""Astra Energy sensors."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import AstraMeterReading
from .const import (
    ATTR_LAST_PROVIDER_UPDATE,
    ATTR_LEGACY_METER_ID,
    ATTR_METER_ID,
    ATTR_RAW_METER_ID,
    ATTR_SOURCE,
    DOMAIN,
    SENSOR_DISPLAY_NAMES,
    SENSOR_OBJECT_IDS,
)
from .coordinator import AstraEnergyCoordinator


@dataclass(frozen=True, kw_only=True)
class AstraSensorEntityDescription(SensorEntityDescription):
    """Astra sensor description."""

    value_attr: str


SENSOR_DESCRIPTIONS: tuple[AstraSensorEntityDescription, ...] = (
    AstraSensorEntityDescription(
        key="power",
        translation_key="power",
        value_attr="power_w",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    AstraSensorEntityDescription(
        key="imported_energy",
        translation_key="imported_energy",
        value_attr="grid_kwh_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AstraSensorEntityDescription(
        key="solar_energy",
        translation_key="solar_energy",
        value_attr="solar_kwh_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AstraSensorEntityDescription(
        key="total_energy",
        translation_key="total_energy",
        value_attr="total_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AstraSensorEntityDescription(
        key="exported_energy",
        translation_key="exported_energy",
        value_attr="exported_kwh_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up Astra Energy sensors."""
    coordinator: AstraEnergyCoordinator = entry.runtime_data
    known_meter_ids: set[str] = set()

    def _add_new_entities() -> None:
        entities: list[AstraEnergySensor] = []
        for reading in coordinator.data.values():
            if reading.meter_id in known_meter_ids:
                continue
            known_meter_ids.add(reading.meter_id)
            entities.extend(
                AstraEnergySensor(coordinator, reading.meter_id, description)
                for description in SENSOR_DESCRIPTIONS
            )
        if entities:
            async_add_entities(entities)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


class AstraEnergySensor(CoordinatorEntity[AstraEnergyCoordinator], SensorEntity):
    """Sensor backed by one Astra meter field."""

    entity_description: AstraSensorEntityDescription
    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: AstraEnergyCoordinator,
        meter_id: str,
        description: AstraSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self._meter_id = meter_id
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{meter_id}_{description.key}"
        self._attr_name = SENSOR_DISPLAY_NAMES[description.key]
        self._attr_suggested_object_id = SENSOR_OBJECT_IDS[description.key]

    @property
    def reading(self) -> AstraMeterReading | None:
        """Return the latest reading for this sensor."""
        return self.coordinator.data.get(self._meter_id)

    @property
    def name(self) -> str | None:
        """Return a friendly name."""
        return SENSOR_DISPLAY_NAMES[self.entity_description.key]

    @property
    def native_value(self):
        """Return sensor value."""
        reading = self.reading
        if reading is None:
            return None
        return getattr(reading, self.entity_description.value_attr)

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Return debug-safe state attributes."""
        reading = self.reading
        if reading is None:
            return {ATTR_METER_ID: self._meter_id, ATTR_SOURCE: DOMAIN}
        return {
            ATTR_METER_ID: reading.meter_id,
            ATTR_RAW_METER_ID: reading.raw_meter_id,
            ATTR_LEGACY_METER_ID: reading.legacy_meter_id,
            ATTR_LAST_PROVIDER_UPDATE: reading.timestamp.isoformat() if reading.timestamp else None,
            ATTR_SOURCE: DOMAIN,
        }

    @property
    def device_info(self):
        """Return device information."""
        reading = self.reading
        return {
            "identifiers": {(DOMAIN, self._meter_id)},
            "manufacturer": "Astra",
            "model": "Energy meter",
            "name": "Astra Energy Meter",
            "serial_number": reading.raw_meter_id if reading else self._meter_id,
        }
