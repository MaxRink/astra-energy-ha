"""Constants for the Astra Energy integration."""

from __future__ import annotations

DOMAIN = "astra_energy"

CONF_BASE_URL = "base_url"
CONF_POLL_INTERVAL = "poll_interval"
CONF_BACKFILL_DAYS = "backfill_days"
CONF_RECENT_REFRESH_HOURS = "recent_refresh_hours"
CONF_HISTORY_GRANULARITY = "history_granularity"
CONF_IMPORT_STATISTICS = "import_statistics"
CONF_GRID_PRICE_NET = "grid_price_net"
CONF_SOLAR_PRICE_NET = "solar_price_net"
CONF_TAX_RATE = "tax_rate"
CONF_MAX_INTERVAL_AVERAGE_KW = "max_interval_average_kw"
CONF_SMOOTH_INTERVAL_ANOMALIES = "smooth_interval_anomalies"
CONF_ANOMALY_REDISTRIBUTION_WINDOW = "anomaly_redistribution_window"
CONF_SMOOTHING_LOOKAROUND_DAYS = "smoothing_lookaround_days"
CONF_CACHE_INTERVAL_PAYLOADS = "cache_interval_payloads"
CONF_CONFIG_ENTRY_ID = "config_entry_id"
CONF_RUN_IN_BACKGROUND = "run_in_background"

HISTORY_GRANULARITY_MONTHLY = "monthly"
HISTORY_GRANULARITY_QUARTER_HOUR = "quarter_hour"
HISTORY_GRANULARITIES = [
    HISTORY_GRANULARITY_MONTHLY,
    HISTORY_GRANULARITY_QUARTER_HOUR,
]

DEFAULT_BASE_URL = "https://astra-cloud.com/readyxnet/source/login/csandroid.php"
DEFAULT_POLL_INTERVAL = 900
DEFAULT_BACKFILL_DAYS = 7
DEFAULT_RECENT_REFRESH_HOURS = 24
DEFAULT_HISTORY_GRANULARITY = HISTORY_GRANULARITY_MONTHLY
DEFAULT_IMPORT_STATISTICS = False
DEFAULT_GRID_PRICE_NET = 0.294
DEFAULT_SOLAR_PRICE_NET = 0.21
DEFAULT_TAX_RATE = 0.19
DEFAULT_MAX_INTERVAL_AVERAGE_KW = 50.0
DEFAULT_SMOOTH_INTERVAL_ANOMALIES = True
DEFAULT_ANOMALY_REDISTRIBUTION_WINDOW = 96
DEFAULT_SMOOTHING_LOOKAROUND_DAYS = 5
DEFAULT_CACHE_INTERVAL_PAYLOADS = True

MIN_POLL_INTERVAL = 60
MAX_BACKFILL_DAYS = 3650
MAX_RECENT_REFRESH_HOURS = 168
MIN_PRICE_NET = 0.0
MAX_PRICE_NET = 10.0
MIN_TAX_RATE = 0.0
MAX_TAX_RATE = 1.0
MIN_MAX_INTERVAL_AVERAGE_KW = 1.0
MAX_MAX_INTERVAL_AVERAGE_KW = 1000.0
MIN_ANOMALY_REDISTRIBUTION_WINDOW = 1
MAX_ANOMALY_REDISTRIBUTION_WINDOW = 672
MIN_SMOOTHING_LOOKAROUND_DAYS = 0
MAX_SMOOTHING_LOOKAROUND_DAYS = 14

DAILY_INTERVAL_CONCURRENCY = 8

ATTR_METER_ID = "meter_id"
ATTR_RAW_METER_ID = "raw_meter_id"
ATTR_LEGACY_METER_ID = "legacy_meter_id"
ATTR_LAST_PROVIDER_UPDATE = "last_provider_update"
ATTR_SOURCE = "source"

SENSOR_DISPLAY_NAMES = {
    "power": "Astra Power",
    "imported_energy": "Astra Grid Energy",
    "solar_energy": "Astra Solar Energy",
    "total_energy": "Astra Total Energy",
    "exported_energy": "Astra Exported Energy",
    "unsmoothed_imported_energy": "Astra Unsmoothed Grid Energy",
    "unsmoothed_solar_energy": "Astra Unsmoothed Solar Energy",
    "unsmoothed_total_energy": "Astra Unsmoothed Total Energy",
    "raw_grid_energy": "Astra Raw Grid Meter Energy",
    "grid_price": "Astra Grid Energy Price",
    "solar_price": "Astra Solar Energy Price",
    "grid_energy_cost_total": "Astra Grid Energy Cost Total",
    "solar_energy_cost_total": "Astra Solar Energy Cost Total",
    "total_energy_cost_total": "Astra Total Energy Cost Total",
    "current_month_grid_energy": "Astra Current Month Grid Energy",
    "current_month_solar_energy": "Astra Current Month Solar Energy",
    "current_month_total_energy": "Astra Current Month Total Energy",
    "current_month_grid_cost": "Astra Current Month Grid Cost",
    "current_month_solar_cost": "Astra Current Month Solar Cost",
    "current_month_total_cost": "Astra Current Month Total Cost",
    "current_year_grid_energy": "Astra Current Year Grid Energy",
    "current_year_solar_energy": "Astra Current Year Solar Energy",
    "current_year_total_energy": "Astra Current Year Total Energy",
    "current_year_raw_grid_energy": "Astra Current Year Raw Grid Energy",
    "current_year_grid_cost": "Astra Current Year Grid Cost",
    "current_year_solar_cost": "Astra Current Year Solar Cost",
    "current_year_total_cost": "Astra Current Year Total Cost",
    "autarky": "Astra Autarky",
    "pv_co2_savings": "Astra PV CO2 Savings",
    "tax_rate": "Astra Energy Tax Rate",
}
SENSOR_OBJECT_IDS = {
    "power": "astra_power",
    "imported_energy": "astra_grid_energy",
    "solar_energy": "astra_solar_energy",
    "total_energy": "astra_total_energy",
    "exported_energy": "astra_exported_energy",
    "unsmoothed_imported_energy": "astra_unsmoothed_grid_energy",
    "unsmoothed_solar_energy": "astra_unsmoothed_solar_energy",
    "unsmoothed_total_energy": "astra_unsmoothed_total_energy",
    "raw_grid_energy": "astra_raw_grid_meter_energy",
    "grid_price": "astra_grid_energy_price",
    "solar_price": "astra_solar_energy_price",
    "grid_energy_cost_total": "astra_grid_energy_cost_total",
    "solar_energy_cost_total": "astra_solar_energy_cost_total",
    "total_energy_cost_total": "astra_total_energy_cost_total",
    "current_month_grid_energy": "astra_current_month_grid_energy",
    "current_month_solar_energy": "astra_current_month_solar_energy",
    "current_month_total_energy": "astra_current_month_total_energy",
    "current_month_grid_cost": "astra_current_month_grid_cost",
    "current_month_solar_cost": "astra_current_month_solar_cost",
    "current_month_total_cost": "astra_current_month_total_cost",
    "current_year_grid_energy": "astra_current_year_grid_energy",
    "current_year_solar_energy": "astra_current_year_solar_energy",
    "current_year_total_energy": "astra_current_year_total_energy",
    "current_year_raw_grid_energy": "astra_current_year_raw_grid_energy",
    "current_year_grid_cost": "astra_current_year_grid_cost",
    "current_year_solar_cost": "astra_current_year_solar_cost",
    "current_year_total_cost": "astra_current_year_total_cost",
    "autarky": "astra_autarky",
    "pv_co2_savings": "astra_pv_co2_savings",
    "tax_rate": "astra_energy_tax_rate",
}
SENSOR_STATISTIC_LABELS = {
    "imported_energy": "grid energy",
    "solar_energy": "solar energy",
    "total_energy": "total energy",
    "unsmoothed_imported_energy": "unsmoothed grid energy",
    "unsmoothed_solar_energy": "unsmoothed solar energy",
    "unsmoothed_total_energy": "unsmoothed total energy",
    "grid_energy_cost_total": "grid energy cost",
    "solar_energy_cost_total": "solar energy cost",
    "total_energy_cost_total": "total energy cost",
}

ISSUE_API_AUTH = "api_auth_failed"
ISSUE_API_UNAVAILABLE = "api_unavailable"
ISSUE_BACKFILL_FAILED = "backfill_failed"

SERVICE_BACKFILL_HISTORY = "backfill_history"

PLATFORMS = ["sensor"]
