"""Astra browser-proxy fallback client."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from .api import ASTRA_TIME_ZONE, AstraApiError, AstraMeterReading, _round_or_none
from .const import (
    DEFAULT_GRID_PRICE_NET,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_SOLAR_PRICE_NET,
    DEFAULT_TAX_RATE,
)

if TYPE_CHECKING:
    from aiohttp import ClientSession


class AstraBrowserProxyError(AstraApiError):
    """The local Astra browser proxy failed or returned unusable data."""


async def async_fetch_browser_proxy_readings(
    session: ClientSession,
    *,
    url: str,
    token: str | None,
    grid_price_net: float = DEFAULT_GRID_PRICE_NET,
    solar_price_net: float = DEFAULT_SOLAR_PRICE_NET,
    tax_rate: float = DEFAULT_TAX_RATE,
) -> list[AstraMeterReading]:
    """Fetch current meter readings from the local browser proxy."""
    if not url:
        raise AstraBrowserProxyError("Astra browser proxy URL is not configured")

    endpoint = f"{url.rstrip('/')}/current"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with session.get(
            endpoint,
            headers=headers,
            timeout=DEFAULT_REQUEST_TIMEOUT,
        ) as response:
            payload = await response.json(content_type=None)
            if response.status >= 400:
                message = payload.get("error") if isinstance(payload, dict) else None
                raise AstraBrowserProxyError(
                    f"Astra browser proxy returned HTTP {response.status}: "
                    f"{message or 'unknown error'}"
                )
    except AstraBrowserProxyError:
        raise
    except Exception as err:  # noqa: BLE001
        raise AstraBrowserProxyError(
            f"Astra browser proxy request failed: {type(err).__name__}: {err}"
        ) from err

    return parse_browser_proxy_payload(
        payload,
        grid_price_net=grid_price_net,
        solar_price_net=solar_price_net,
        tax_rate=tax_rate,
    )


def parse_browser_proxy_payload(
    payload: Any,
    *,
    grid_price_net: float = DEFAULT_GRID_PRICE_NET,
    solar_price_net: float = DEFAULT_SOLAR_PRICE_NET,
    tax_rate: float = DEFAULT_TAX_RATE,
) -> list[AstraMeterReading]:
    """Parse the browser-proxy JSON payload into normalized readings."""
    if not isinstance(payload, dict):
        raise AstraBrowserProxyError("Astra browser proxy returned a non-object payload")
    if payload.get("ok") is not True:
        raise AstraBrowserProxyError(
            str(payload.get("error") or "Astra browser proxy returned an error")
        )
    meter = payload.get("meter")
    if not isinstance(meter, dict):
        raise AstraBrowserProxyError("Astra browser proxy response is missing meter data")

    meter_id = str(meter.get("meter_id") or "").strip()
    if not meter_id:
        raise AstraBrowserProxyError("Astra browser proxy response is missing meter_id")
    timestamp = _parse_timestamp(meter.get("timestamp"))
    total = _float_or_none(meter.get("total_kwh"))
    solar = _float_or_none(meter.get("solar_kwh"))
    grid = _float_or_none(meter.get("grid_kwh"))
    raw_grid = _float_or_none(meter.get("raw_grid_kwh"))
    if grid is None and total is not None and solar is not None:
        grid = max(total - solar, 0.0)
    if total is None and (grid is not None or solar is not None):
        total = (grid or 0.0) + (solar or 0.0)
    if all(value is None for value in (grid, solar, total)):
        raise AstraBrowserProxyError(
            "Astra browser proxy response contains no usable cumulative meter values"
        )

    grid_price_gross = _round_or_none(grid_price_net * (1 + tax_rate))
    solar_price_gross = _round_or_none(solar_price_net * (1 + tax_rate))
    month_grid = _float_or_none(meter.get("current_month_grid_kwh"))
    month_solar = _float_or_none(meter.get("current_month_solar_kwh"))
    month_total = _float_or_none(meter.get("current_month_total_kwh"))
    year_grid = _float_or_none(meter.get("current_year_grid_kwh"))
    year_solar = _float_or_none(meter.get("current_year_solar_kwh"))
    year_total = _float_or_none(meter.get("current_year_total_kwh"))

    return [
        AstraMeterReading(
            meter_id=meter_id,
            meter_name=str(meter.get("meter_name") or "Astra Energy Meter"),
            timestamp=timestamp,
            power_w=None,
            imported_kwh_total=grid,
            grid_kwh_total=grid,
            solar_kwh_total=solar,
            total_kwh=total,
            unsmoothed_grid_kwh_total=raw_grid or grid,
            unsmoothed_solar_kwh_total=solar,
            unsmoothed_total_kwh=total,
            raw_grid_kwh_total=raw_grid,
            grid_price_net_eur_per_kwh=grid_price_net,
            grid_price_gross_eur_per_kwh=grid_price_gross,
            solar_price_net_eur_per_kwh=solar_price_net,
            solar_price_gross_eur_per_kwh=solar_price_gross,
            tax_rate=tax_rate,
            grid_cost_total_gross_eur=_cost(grid, grid_price_gross),
            solar_cost_total_gross_eur=_cost(solar, solar_price_gross),
            total_cost_total_gross_eur=_sum_costs(
                _cost(grid, grid_price_gross),
                _cost(solar, solar_price_gross),
            ),
            current_month_grid_kwh=month_grid,
            current_month_solar_kwh=month_solar,
            current_month_total_kwh=month_total,
            current_month_raw_grid_kwh=_float_or_none(
                meter.get("current_month_raw_grid_kwh")
            ),
            current_month_grid_cost_gross_eur=_cost(month_grid, grid_price_gross),
            current_month_solar_cost_gross_eur=_cost(month_solar, solar_price_gross),
            current_month_total_cost_gross_eur=_sum_costs(
                _cost(month_grid, grid_price_gross),
                _cost(month_solar, solar_price_gross),
            ),
            current_year_grid_kwh=year_grid,
            current_year_solar_kwh=year_solar,
            current_year_total_kwh=year_total,
            current_year_raw_grid_kwh=_float_or_none(meter.get("current_year_raw_grid_kwh")),
            current_year_grid_cost_gross_eur=_cost(year_grid, grid_price_gross),
            current_year_solar_cost_gross_eur=_cost(year_solar, solar_price_gross),
            current_year_total_cost_gross_eur=_sum_costs(
                _cost(year_grid, grid_price_gross),
                _cost(year_solar, solar_price_gross),
            ),
            autarky_percent=_float_or_none(meter.get("autarky_percent")),
            pv_co2_savings_t=_float_or_none(meter.get("pv_co2_savings_t")),
            raw_meter_id=str(meter.get("raw_meter_id") or meter_id),
            raw={
                "source": "browser_proxy",
                "proxy_source": payload.get("source"),
                "fetched_at": payload.get("fetched_at"),
            },
        )
    ]


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise AstraBrowserProxyError("Astra browser proxy timestamp is not a string")
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as err:
        raise AstraBrowserProxyError(
            "Astra browser proxy timestamp is not ISO-8601"
        ) from err
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=ASTRA_TIME_ZONE)
    return timestamp


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as err:
        raise AstraBrowserProxyError(
            f"Astra browser proxy numeric value is invalid: {value!r}"
        ) from err


def _cost(value: float | None, price: float | None) -> float | None:
    if value is None or price is None:
        return None
    return _round_or_none(value * price, 4)


def _sum_costs(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return _round_or_none(sum(present), 4)
