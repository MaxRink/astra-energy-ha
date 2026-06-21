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
from homeassistant.helpers.entity import EntityCategory
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


@dataclass(frozen=True, kw_only=True)
class AstraCoordinatorSensorEntityDescription(SensorEntityDescription):
    """Coordinator-level Astra diagnostic sensor description."""


COORDINATOR_SENSOR_DESCRIPTIONS: tuple[AstraCoordinatorSensorEntityDescription, ...] = (
    AstraCoordinatorSensorEntityDescription(
        key="api_status",
        translation_key="api_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AstraCoordinatorSensorEntityDescription(
        key="last_successful_source",
        translation_key="last_successful_source",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AstraCoordinatorSensorEntityDescription(
        key="web_session_status",
        translation_key="web_session_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


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
        key="unsmoothed_imported_energy",
        translation_key="unsmoothed_imported_energy",
        value_attr="unsmoothed_grid_kwh_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AstraSensorEntityDescription(
        key="unsmoothed_solar_energy",
        translation_key="unsmoothed_solar_energy",
        value_attr="unsmoothed_solar_kwh_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AstraSensorEntityDescription(
        key="unsmoothed_total_energy",
        translation_key="unsmoothed_total_energy",
        value_attr="unsmoothed_total_kwh",
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
    AstraSensorEntityDescription(
        key="raw_grid_energy",
        translation_key="raw_grid_energy",
        value_attr="raw_grid_kwh_total",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="grid_price",
        translation_key="grid_price",
        value_attr="grid_price_gross_eur_per_kwh",
        native_unit_of_measurement="EUR/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=5,
    ),
    AstraSensorEntityDescription(
        key="solar_price",
        translation_key="solar_price",
        value_attr="solar_price_gross_eur_per_kwh",
        native_unit_of_measurement="EUR/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=5,
    ),
    AstraSensorEntityDescription(
        key="grid_energy_cost_total",
        translation_key="grid_energy_cost_total",
        value_attr="grid_cost_total_gross_eur",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="solar_energy_cost_total",
        translation_key="solar_energy_cost_total",
        value_attr="solar_cost_total_gross_eur",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="total_energy_cost_total",
        translation_key="total_energy_cost_total",
        value_attr="total_cost_total_gross_eur",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="current_month_grid_energy",
        translation_key="current_month_grid_energy",
        value_attr="current_month_grid_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="current_month_solar_energy",
        translation_key="current_month_solar_energy",
        value_attr="current_month_solar_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="current_month_total_energy",
        translation_key="current_month_total_energy",
        value_attr="current_month_total_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="current_month_grid_cost",
        translation_key="current_month_grid_cost",
        value_attr="current_month_grid_cost_gross_eur",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="current_month_solar_cost",
        translation_key="current_month_solar_cost",
        value_attr="current_month_solar_cost_gross_eur",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="current_month_total_cost",
        translation_key="current_month_total_cost",
        value_attr="current_month_total_cost_gross_eur",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="current_year_grid_energy",
        translation_key="current_year_grid_energy",
        value_attr="current_year_grid_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="current_year_solar_energy",
        translation_key="current_year_solar_energy",
        value_attr="current_year_solar_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="current_year_total_energy",
        translation_key="current_year_total_energy",
        value_attr="current_year_total_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="current_year_raw_grid_energy",
        translation_key="current_year_raw_grid_energy",
        value_attr="current_year_raw_grid_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="current_year_grid_cost",
        translation_key="current_year_grid_cost",
        value_attr="current_year_grid_cost_gross_eur",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="current_year_solar_cost",
        translation_key="current_year_solar_cost",
        value_attr="current_year_solar_cost_gross_eur",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="current_year_total_cost",
        translation_key="current_year_total_cost",
        value_attr="current_year_total_cost_gross_eur",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
    ),
    AstraSensorEntityDescription(
        key="autarky",
        translation_key="autarky",
        value_attr="autarky_percent",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AstraSensorEntityDescription(
        key="pv_co2_savings",
        translation_key="pv_co2_savings",
        value_attr="pv_co2_savings_t",
        native_unit_of_measurement="t",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AstraSensorEntityDescription(
        key="tax_rate",
        translation_key="tax_rate",
        value_attr="tax_rate",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Set up Astra Energy sensors."""
    coordinator: AstraEnergyCoordinator = entry.runtime_data
    known_meter_ids: set[str] = set()
    async_add_entities(
        AstraCoordinatorSensor(coordinator, description)
        for description in COORDINATOR_SENSOR_DESCRIPTIONS
    )

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
        value = getattr(reading, self.entity_description.value_attr)
        if self.entity_description.key == "tax_rate" and value is not None:
            return value * 100
        return value

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Return debug-safe state attributes."""
        reading = self.reading
        if reading is None:
            return {ATTR_METER_ID: self._meter_id, ATTR_SOURCE: DOMAIN}
        attributes = {
            ATTR_METER_ID: reading.meter_id,
            ATTR_RAW_METER_ID: reading.raw_meter_id,
            ATTR_LEGACY_METER_ID: reading.legacy_meter_id,
            ATTR_LAST_PROVIDER_UPDATE: reading.timestamp.isoformat() if reading.timestamp else None,
            ATTR_SOURCE: DOMAIN,
        }
        if self.entity_description.key in {"grid_price", "solar_price", "tax_rate"}:
            attributes.update(
                {
                    "grid_price_net_eur_per_kwh": reading.grid_price_net_eur_per_kwh,
                    "solar_price_net_eur_per_kwh": reading.solar_price_net_eur_per_kwh,
                    "tax_rate": reading.tax_rate,
                    "price_includes_tax": self.entity_description.key != "tax_rate",
                    "price_source": "configured_observed_astra_tariff",
                }
            )
        return attributes

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


class AstraCoordinatorSensor(CoordinatorEntity[AstraEnergyCoordinator], SensorEntity):
    """Sensor backed by coordinator status rather than one meter field."""

    entity_description: AstraCoordinatorSensorEntityDescription
    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: AstraEnergyCoordinator,
        description: AstraCoordinatorSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{description.key}"
        self._attr_name = SENSOR_DISPLAY_NAMES[description.key]
        self._attr_suggested_object_id = SENSOR_OBJECT_IDS[description.key]

    @property
    def name(self) -> str | None:
        """Return a friendly name."""
        return SENSOR_DISPLAY_NAMES[self.entity_description.key]

    @property
    def native_value(self):
        """Return coordinator status."""
        if self.entity_description.key == "api_status":
            return self.coordinator.api_status
        if self.entity_description.key == "last_successful_source":
            return self.coordinator.last_successful_source
        if self.entity_description.key == "web_session_status":
            return self.coordinator.web_session_status.get("status")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return debug-safe coordinator status attributes."""
        attributes: dict[str, object] = {ATTR_SOURCE: DOMAIN}
        if self.entity_description.key == "api_status":
            attributes["last_error"] = self.coordinator.last_error
            attributes["last_update_success"] = self.coordinator.last_update_success
        if self.entity_description.key == "web_session_status":
            attributes.update(self.coordinator.web_session_status)
        return attributes

    @property
    def device_info(self):
        """Return integration device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.config_entry.entry_id)},
            "manufacturer": "Astra",
            "model": "Energy integration",
            "name": "Astra Energy",
        }
