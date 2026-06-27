"""Astra Energy integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval
import voluptuous as vol

from .const import (
    CONF_ANOMALY_REDISTRIBUTION_WINDOW,
    CONF_BACKFILL_DAYS,
    CONF_BASE_URL,
    CONF_CACHE_INTERVAL_PAYLOADS,
    CONF_CONFIG_ENTRY_ID,
    CONF_HISTORY_GRANULARITY,
    CONF_IMPORT_STATISTICS,
    CONF_MAX_INTERVAL_AVERAGE_KW,
    CONF_POLL_INTERVAL,
    CONF_RECENT_REFRESH_HOURS,
    CONF_RUN_IN_BACKGROUND,
    CONF_SMOOTH_INTERVAL_ANOMALIES,
    CONF_SMOOTHING_LOOKAROUND_DAYS,
    DEFAULT_BACKFILL_DAYS,
    DEFAULT_HISTORY_GRANULARITY,
    DEFAULT_IMPORT_STATISTICS,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_RECENT_REFRESH_HOURS,
    DOMAIN,
    HISTORY_GRANULARITIES,
    MAX_ANOMALY_REDISTRIBUTION_WINDOW,
    MAX_MAX_INTERVAL_AVERAGE_KW,
    MAX_RECENT_REFRESH_HOURS,
    MAX_SMOOTHING_LOOKAROUND_DAYS,
    MIN_ANOMALY_REDISTRIBUTION_WINDOW,
    MIN_MAX_INTERVAL_AVERAGE_KW,
    MIN_SMOOTHING_LOOKAROUND_DAYS,
    SERVICE_BACKFILL_HISTORY,
)
from .coordinator import AstraEnergyCoordinator
from .statistics import async_backfill_statistics

AstraEnergyConfigEntry = ConfigEntry[AstraEnergyCoordinator]

_LOGGER = logging.getLogger(__name__)

_CONF_BACKFILL_DAYS_ALIASES = (CONF_BACKFILL_DAYS, "days")
_LEGACY_DEFAULT_POLL_INTERVAL = 900

_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("days"): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(CONF_BACKFILL_DAYS): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(CONF_RECENT_REFRESH_HOURS): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=MAX_RECENT_REFRESH_HOURS)
        ),
        vol.Optional(CONF_IMPORT_STATISTICS): bool,
        vol.Optional(CONF_HISTORY_GRANULARITY): vol.In(HISTORY_GRANULARITIES),
        vol.Optional(CONF_MAX_INTERVAL_AVERAGE_KW): vol.All(
            vol.Coerce(float),
            vol.Range(min=MIN_MAX_INTERVAL_AVERAGE_KW, max=MAX_MAX_INTERVAL_AVERAGE_KW),
        ),
        vol.Optional(CONF_SMOOTH_INTERVAL_ANOMALIES): bool,
        vol.Optional(CONF_ANOMALY_REDISTRIBUTION_WINDOW): vol.All(
            vol.Coerce(int),
            vol.Range(
                min=MIN_ANOMALY_REDISTRIBUTION_WINDOW,
                max=MAX_ANOMALY_REDISTRIBUTION_WINDOW,
            ),
        ),
        vol.Optional(CONF_SMOOTHING_LOOKAROUND_DAYS): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_SMOOTHING_LOOKAROUND_DAYS, max=MAX_SMOOTHING_LOOKAROUND_DAYS),
        ),
        vol.Optional(CONF_CACHE_INTERVAL_PAYLOADS): bool,
        vol.Optional(CONF_CONFIG_ENTRY_ID): str,
        vol.Optional(CONF_RUN_IN_BACKGROUND, default=False): bool,
    }
)


def _service_value(data: dict, keys: tuple[str, ...] | str, default):
    """Return a service value with support for backwards-compatible aliases."""
    if isinstance(keys, str):
        keys = (keys,)
    for key in keys:
        if key in data:
            return data[key]
    return default


def _normalize_entry_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Move old default options to current safer defaults."""
    if entry.options.get(CONF_POLL_INTERVAL) != _LEGACY_DEFAULT_POLL_INTERVAL:
        return
    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL},
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
        days = _service_value(
            call.data,
            _CONF_BACKFILL_DAYS_ALIASES,
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
            max_average_kw=call.data.get(CONF_MAX_INTERVAL_AVERAGE_KW),
            smooth_anomalies=call.data.get(CONF_SMOOTH_INTERVAL_ANOMALIES),
            redistribution_window=call.data.get(CONF_ANOMALY_REDISTRIBUTION_WINDOW),
            smoothing_lookaround_days=call.data.get(CONF_SMOOTHING_LOOKAROUND_DAYS),
            cache_interval_payloads=call.data.get(CONF_CACHE_INTERVAL_PAYLOADS),
        )
    return response


async def _async_background_backfill(hass: HomeAssistant, call: ServiceCall) -> None:
    """Run a backfill task in the background and let HA log unexpected failures."""
    await _async_backfill_history(hass, call)


async def _async_background_initial_refresh(coordinator: AstraEnergyCoordinator) -> None:
    """Run the initial provider update without blocking config-entry setup."""
    try:
        await coordinator.async_refresh()
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Astra Energy initial refresh failed")


async def _async_run_configured_backfill(hass: HomeAssistant, entry_id: str) -> None:
    """Run the configured statistics backfill for one entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    if coordinator is None:
        return
    entry = coordinator.config_entry
    if not entry.options.get(CONF_IMPORT_STATISTICS, DEFAULT_IMPORT_STATISTICS):
        return
    if getattr(coordinator, "_scheduled_backfill_running", False):
        return
    coordinator._scheduled_backfill_running = True
    try:
        await async_backfill_statistics(
            hass,
            coordinator,
            days=entry.options.get(CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS),
            recent_refresh_hours=entry.options.get(
                CONF_RECENT_REFRESH_HOURS, DEFAULT_RECENT_REFRESH_HOURS
            ),
            history_granularity=entry.options.get(
                CONF_HISTORY_GRANULARITY, DEFAULT_HISTORY_GRANULARITY
            ),
            import_statistics=True,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Astra Energy scheduled backfill failed")
    finally:
        coordinator._scheduled_backfill_running = False


async def async_setup_entry(hass: HomeAssistant, entry: AstraEnergyConfigEntry) -> bool:
    """Set up Astra Energy from a config entry."""
    _normalize_entry_options(hass, entry)
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
    entry.runtime_data = coordinator
    coordinator.data = coordinator.data or {}
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    initial_refresh_task = hass.async_create_task(_async_background_initial_refresh(coordinator))

    def _cancel_initial_refresh() -> None:
        initial_refresh_task.cancel()

    entry.async_on_unload(_cancel_initial_refresh)

    if entry.options.get(CONF_IMPORT_STATISTICS, DEFAULT_IMPORT_STATISTICS):

        async def _async_scheduled_backfill(_now) -> None:
            await _async_run_configured_backfill(hass, entry.entry_id)

        backfill_interval = timedelta(
            seconds=max(entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL), 3600)
        )
        entry.async_on_unload(
            async_track_time_interval(hass, _async_scheduled_backfill, backfill_interval)
        )

        async def _async_run_initial_backfill() -> None:
            try:
                await initial_refresh_task
            except asyncio.CancelledError:
                return
            await _async_run_configured_backfill(hass, entry.entry_id)

        initial_backfill_task = hass.async_create_task(_async_run_initial_backfill())

        def _cancel_initial_backfill() -> None:
            initial_backfill_task.cancel()

        entry.async_on_unload(_cancel_initial_backfill)

    if not hass.services.has_service(DOMAIN, SERVICE_BACKFILL_HISTORY):

        async def _async_handle_backfill(call: ServiceCall) -> dict[str, dict[str, int]]:
            if call.data.get(CONF_RUN_IN_BACKGROUND):
                hass.async_create_task(_async_background_backfill(hass, call))
                return {"started": {"entries": len(hass.data.get(DOMAIN, {}))}}
            return await _async_backfill_history(hass, call)

        hass.services.async_register(
            DOMAIN,
            SERVICE_BACKFILL_HISTORY,
            _async_handle_backfill,
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
