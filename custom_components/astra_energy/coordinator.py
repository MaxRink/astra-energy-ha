"""Coordinator for Astra Energy."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AstraApiError, AstraAuthError, AstraClient, AstraMeterReading
from .const import DOMAIN, ISSUE_API_AUTH, ISSUE_API_UNAVAILABLE
from .reporting import async_create_issue, async_delete_issue, error_payload

_LOGGER = logging.getLogger(__name__)


class AstraEnergyCoordinator(DataUpdateCoordinator[dict[str, AstraMeterReading]]):
    """Fetch and normalize Astra meter readings."""

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        entry,
        username: str,
        password: str,
        base_url: str,
        update_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=update_interval,
        )
        self.client = AstraClient(
            async_get_clientsession(hass),
            username=username,
            password=password,
            base_url=base_url,
        )
        self.last_error: dict[str, str] | None = None

    async def _async_update_data(self) -> dict[str, AstraMeterReading]:
        """Fetch latest Astra data."""
        try:
            readings = await self.client.async_get_meters()
        except AstraAuthError as err:
            self.last_error = error_payload(err)
            await async_create_issue(
                self.hass,
                ISSUE_API_AUTH,
                translation_key=ISSUE_API_AUTH,
                placeholders={"error": str(err)},
                notification_title="Astra Energy authentication failed",
                notification_message=(
                    "Astra rejected the stored credentials. Reauthenticate the "
                    "Astra Energy integration from Settings > Devices & services."
                ),
            )
            raise ConfigEntryAuthFailed(str(err)) from err
        except AstraApiError as err:
            self.last_error = error_payload(err)
            await async_create_issue(
                self.hass,
                ISSUE_API_UNAVAILABLE,
                translation_key=ISSUE_API_UNAVAILABLE,
                placeholders={"error": str(err)},
                notification_title="Astra Energy update failed",
                notification_message=(
                    "Astra Energy could not fetch meter data. Home Assistant will "
                    "retry automatically. Last error: "
                    f"{type(err).__name__}: {err}"
                ),
            )
            raise UpdateFailed(str(err)) from err

        self.last_error = None
        await async_delete_issue(self.hass, ISSUE_API_AUTH)
        await async_delete_issue(self.hass, ISSUE_API_UNAVAILABLE)
        return {reading.meter_id: reading for reading in readings}
