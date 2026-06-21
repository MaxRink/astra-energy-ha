"""Home Assistant-facing issue and notification reporting."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def utcnow_iso() -> str:
    """Return current UTC timestamp as ISO string."""
    return dt_util.utcnow().isoformat()


def error_payload(err: Exception) -> dict[str, str]:
    """Return a redaction-safe error payload for diagnostics."""
    return {
        "type": type(err).__name__,
        "message": str(err),
        "timestamp": utcnow_iso(),
    }


async def async_create_issue(  # pragma: no cover
    hass: HomeAssistant,
    issue_id: str,
    *,
    translation_key: str,
    severity: str = "error",
    placeholders: dict[str, str] | None = None,
    notification_title: str | None = None,
    notification_message: str | None = None,
) -> None:
    """Create a Home Assistant repair issue and optional persistent notification."""
    try:
        from homeassistant.helpers import issue_registry as ir

        issue_severity = getattr(ir.IssueSeverity, severity.upper())
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=issue_severity,
            translation_key=translation_key,
            translation_placeholders=placeholders or {},
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Could not create Astra Energy repair issue: %s", err)

    if notification_title and notification_message:
        try:
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "notification_id": f"{DOMAIN}_{issue_id}",
                    "title": notification_title,
                    "message": notification_message,
                },
                blocking=False,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not create Astra Energy notification: %s", err)


async def async_delete_issue(  # pragma: no cover
    hass: HomeAssistant, issue_id: str
) -> None:
    """Delete a Home Assistant repair issue and matching persistent notification."""
    try:
        from homeassistant.helpers import issue_registry as ir

        ir.async_delete_issue(hass, DOMAIN, issue_id)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Could not delete Astra Energy repair issue: %s", err)

    try:
        await hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": f"{DOMAIN}_{issue_id}"},
            blocking=False,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Could not dismiss Astra Energy notification: %s", err)


def summarize_counts(counts: dict[str, int]) -> str:
    """Return a compact count summary."""
    if not counts:
        return "no readings"
    return ", ".join(f"{meter_id}: {count}" for meter_id, count in sorted(counts.items()))
