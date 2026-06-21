"""Constants for the Astra Energy integration."""

from __future__ import annotations

DOMAIN = "astra_energy"

CONF_BASE_URL = "base_url"
CONF_POLL_INTERVAL = "poll_interval"
CONF_BACKFILL_DAYS = "backfill_days"
CONF_RECENT_REFRESH_HOURS = "recent_refresh_hours"
CONF_HISTORY_GRANULARITY = "history_granularity"
CONF_IMPORT_STATISTICS = "import_statistics"
CONF_CONFIG_ENTRY_ID = "config_entry_id"

HISTORY_GRANULARITY_MONTHLY = "monthly"
HISTORY_GRANULARITY_QUARTER_HOUR = "quarter_hour"
HISTORY_GRANULARITIES = [
    HISTORY_GRANULARITY_MONTHLY,
    HISTORY_GRANULARITY_QUARTER_HOUR,
]

DEFAULT_BASE_URL = "https://astra-cloud.com/readyxnet/source/login/csandroid.php"
DEFAULT_POLL_INTERVAL = 300
DEFAULT_BACKFILL_DAYS = 7
DEFAULT_RECENT_REFRESH_HOURS = 24
DEFAULT_HISTORY_GRANULARITY = HISTORY_GRANULARITY_MONTHLY
DEFAULT_IMPORT_STATISTICS = False

MIN_POLL_INTERVAL = 60
MAX_BACKFILL_DAYS = 3650
MAX_RECENT_REFRESH_HOURS = 168

ATTR_METER_ID = "meter_id"
ATTR_RAW_METER_ID = "raw_meter_id"
ATTR_LEGACY_METER_ID = "legacy_meter_id"
ATTR_LAST_PROVIDER_UPDATE = "last_provider_update"
ATTR_SOURCE = "source"

ISSUE_API_AUTH = "api_auth_failed"
ISSUE_API_UNAVAILABLE = "api_unavailable"
ISSUE_BACKFILL_FAILED = "backfill_failed"

SERVICE_BACKFILL_HISTORY = "backfill_history"

PLATFORMS = ["sensor"]
