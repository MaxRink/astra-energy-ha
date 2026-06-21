"""Diagnostics for Astra Energy."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from .const import DOMAIN

TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    "access_token",
    "refresh_token",
    "cookie",
    "cookies",
    "session",
    "session_id",
    "raw_meter_id",
}


async def async_get_config_entry_diagnostics(hass, entry) -> dict:
    """Return diagnostics with sensitive fields redacted."""
    coordinator = entry.runtime_data
    data = {
        "entry": {
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "last_update_success": coordinator.last_update_success,
        "last_error": coordinator.last_error,
        "meters": [
            {
                "meter_id": reading.meter_id,
                "raw_meter_id": reading.raw_meter_id,
                "legacy_meter_id": reading.legacy_meter_id,
                "available_channels": [
                    channel
                    for channel, value in {
                        "grid": reading.grid_kwh_total,
                        "solar": reading.solar_kwh_total,
                        "total": reading.total_kwh,
                        "raw_grid": reading.raw_grid_kwh_total,
                        "exported": reading.exported_kwh_total,
                        "grid_price": reading.grid_price_gross_eur_per_kwh,
                        "solar_price": reading.solar_price_gross_eur_per_kwh,
                        "current_month_grid": reading.current_month_grid_kwh,
                        "current_month_solar": reading.current_month_solar_kwh,
                        "current_month_total": reading.current_month_total_kwh,
                        "current_year_grid": reading.current_year_grid_kwh,
                        "current_year_solar": reading.current_year_solar_kwh,
                        "current_year_total": reading.current_year_total_kwh,
                        "autarky": reading.autarky_percent,
                        "pv_co2_savings": reading.pv_co2_savings_t,
                    }.items()
                    if value is not None
                ],
            }
            for reading in (coordinator.data or {}).values()
        ],
        "domain": DOMAIN,
    }
    return async_redact_data(data, TO_REDACT)
