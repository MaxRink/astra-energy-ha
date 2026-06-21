"""Astra Energy integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
import voluptuous as vol

from .const import (
    CONF_BACKFILL_DAYS,
    CONF_BASE_URL,
    CONF_CONFIG_ENTRY_ID,
    CONF_HISTORY_GRANULARITY,
    CONF_IMPORT_STATISTICS,
    CONF_POLL_INTERVAL,
    CONF_RECENT_REFRESH_HOURS,
    DEFAULT_BACKFILL_DAYS,
    DEFAULT_HISTORY_GRANULARITY,
    DEFAULT_IMPORT_STATISTICS,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_RECENT_REFRESH_HOURS,
    DOMAIN,
    HISTORY_GRANULARITIES,
    MAX_RECENT_REFRESH_HOURS,
    SERVICE_BACKFILL_HISTORY,
)
from .coordinator import AstraEnergyCoordinator
from .statistics import async_backfill_statistics

AstraEnergyConfigEntry = ConfigEntry[AstraEnergyCoordinator]

_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_BACKFILL_DAYS): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(CONF_RECENT_REFRESH_HOURS): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=MAX_RECENT_REFRESH_HOURS)
        ),
        vol.Optional(CONF_IMPORT_STATISTICS): bool,
        vol.Optional(CONF_HISTORY_GRANULARITY): vol.In(HISTORY_GRANULARITIES),
        vol.Optional(CONF_CONFIG_ENTRY_ID): str,
    }
)


async def _async_backfill_history(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, dict[str, int]]:
    """Fetch historical readings for one or all loaded Astra entries."""
    coordinators: dict[str, AstraEnergyCoordinator] = hass.data.get(DOMAIN, {})
    if not coordinators:
        raise HomeAssistantError("No loaded Astra Energy entries")

    requested_entry_id = call.data.get(CONF_CONFIG_ENTRY_ID)
    if requested_entry_id:
        coordinator = coordinators.get(requested_entry_id)
        if coordinator is None:
            raise HomeAssistantError(f"Astra Energy entry is not loaded: {requested_entry_id}")
        selected = {requested_entry_id: coordinator}
    else:
        selected = coordinators

    response: dict[str, dict[str, int]] = {}
    for entry_id, coordinator in selected.items():
        entry = coordinator.config_entry
        days = call.data.get(
            CONF_BACKFILL_DAYS,
            entry.options.get(CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS),
        )
        import_statistics = call.data.get(
            CONF_IMPORT_STATISTICS,
            entry.options.get(CONF_IMPORT_STATISTICS, DEFAULT_IMPORT_STATISTICS),
        )
        recent_refresh_hours = call.data.get(
            CONF_RECENT_REFRESH_HOURS,
            entry.options.get(CONF_RECENT_REFRESH_HOURS, DEFAULT_RECENT_REFRESH_HOURS),
        )
        history_granularity = call.data.get(
            CONF_HISTORY_GRANULARITY,
            entry.options.get(CONF_HISTORY_GRANULARITY, DEFAULT_HISTORY_GRANULARITY),
        )
        response[entry_id] = await async_backfill_statistics(
            hass,
            coordinator,
            days=days,
            recent_refresh_hours=recent_refresh_hours,
            history_granularity=history_granularity,
            import_statistics=import_statistics,
        )
    return response


async def async_setup_entry(hass: HomeAssistant, entry: AstraEnergyConfigEntry) -> bool:
    """Set up Astra Energy from a config entry."""
    coordinator = AstraEnergyCoordinator(
        hass=hass,
        entry=entry,
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        base_url=entry.data[CONF_BASE_URL],
        update_interval=timedelta(
            seconds=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        ),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    if not hass.services.has_service(DOMAIN, SERVICE_BACKFILL_HISTORY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_BACKFILL_HISTORY,
            lambda call: _async_backfill_history(hass, call),
            schema=_SERVICE_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AstraEnergyConfigEntry) -> bool:
    """Unload an Astra Energy config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR])
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if unload_ok and not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_BACKFILL_HISTORY)
    return unload_ok
