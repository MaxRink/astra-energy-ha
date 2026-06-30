# Astra Energy for Home Assistant

Custom Home Assistant integration scaffold for monitoring Astra near-live energy usage and exposing Energy Dashboard-compatible sensors.

## Current State

This repository is intentionally split into two tracks:

- `tools/`: discovery utilities for documenting Astra web/app APIs.
- `custom_components/astra_energy/`: Home Assistant integration scaffold backed by the Android JSON API.

Raw captures are ignored by git because they may contain credentials, cookies, tokens, meter identifiers, and private consumption data.

## Local Protocol Probe

The integration uses the Android JSON endpoint discovered from the APK. You can
test that protocol without Home Assistant:

```sh
cp .env.example .secrets.env
# fill ASTRA_USERNAME and ASTRA_PASSWORD in .secrets.env
python3 tools/astra_mobile_probe.py --username "<username>"
```

The script prompts for the password and prints only schema/status metadata.
If `.secrets.env` contains `ASTRA_USERNAME` and `ASTRA_PASSWORD`, the arguments
can be omitted.

To capture all known raw Android API payloads for local analysis:

```sh
python3 tools/astra_raw_dump.py
```

To probe candidate mobile action names without printing raw account data:

```sh
python3 tools/astra_endpoint_discovery.py \
  --actions get_mtr_preis,get_gemeinstrom \
  --out captures/astra-endpoint-discovery-latest.json
```

The dump is written below `captures/`, which is gitignored because it contains
private meter identifiers and consumption data.

Analyze one or more local raw dumps:

```sh
python3 tools/analyze_raw_dump.py captures/astra-raw-2025.json captures/astra-raw-2026.json
```

Live data currently shows one physical meter with Astra subchannels:

- total cumulative energy from the physical meter row
- grid energy derived as total minus `T2` / object/PV usage
- solar/object energy from `T2` / `Objektbezug` / `PV`

The Home Assistant integration exposes those as one device with separate
cumulative `kWh` entities.

Run local tests:

```sh
python3 -m pytest -q
```

## Web API Capture

Launch an isolated Chrome profile with CDP and capture traffic:

```sh
python3 tools/cdp_capture.py \
  --launch-chrome \
  --chrome-path "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --target-url "https://astra-cloud.com/readyxnet/source/login/csloginw.php" \
  --out captures/web-login.jsonl
```

Log in in the opened Chrome window, browse all relevant usage views, then stop the script with `Ctrl-C`.

When the mobile endpoints are unavailable but you have a working browser
session, use the manual cookie fallback without another CDP capture:

```sh
# from a Chrome instance already started with --remote-debugging-port=9222
python3 tools/astra_cdp_cookie_export.py --write-env .secrets.env

# then test the captured session against the web graph endpoint
python3 tools/astra_web_probe.py --start "2026-06-21 00:00:00" --end "2026-06-22 00:00:00"
```

The exporter prints only a redacted summary by default. It writes
`ASTRA_WEB_SESSION_ID` and `ASTRA_WEB_COOKIE` into `.secrets.env`, which is
gitignored. The Home Assistant integration exposes the same web-session fallback
settings in the UI and creates diagnostic sensors plus repair issues when the
stored session is missing, expired, logged out, unreachable, or returning
malformed graph data.

When the mobile API is deferred and web login is blocked by reCAPTCHA, the
integration can use the local persistent-browser sidecar in
`tools/astra_browser_proxy`. The sidecar keeps a browser profile and exposes a
small local JSON API. Configure its base URL in the integration options under
`browser_proxy_url`; options changes reload the integration automatically. Live
cumulative values from this fallback are still checked against the last safe
Home Assistant baseline, and large catch-up gaps are withheld instead of being
published as one Energy Dashboard spike.

Create sanitized API docs from the capture:

```sh
python3 tools/analyze_capture.py captures/web-login.jsonl --out docs/api-web-capture.md
```

OpenAPI references live in:

- `docs/openapi-astra-android.yaml`
- `docs/openapi-web-observed.yaml`

## Android Static Analysis

The app package is `de.astra_software.astracockpit`. APK tooling used here:

```sh
brew install jadx apktool android-platform-tools apkeep
```

With a USB-authorized device:

```sh
adb shell pm path de.astra_software.astracockpit
adb pull <package-path> captures/android/apks/base.apk
jadx -d captures/android/jadx/base captures/android/apks/base.apk
apktool d -f -o captures/android/apktool/base captures/android/apks/base.apk
```

The iOS app is installed locally as `/Applications/astracockpit.app`. Static
analysis of its wrapped binary confirms a native Swift app, not a WebView, and
finds the mobile endpoint
`https://astra-cloud.com/readyxnet/source/login/csios.php`. The iOS binary uses
the same `SNAFU` + MD5 signed form protocol as Android and exposes the same core
energy feature set: consumption overview, consumption by medium, energy
balance, autarky, historical trends, meter status, object/location, weather,
quarter-hour values, and object/grid split controls. Details are documented in
`docs/api.md`.

## Home Assistant Development

### HACS Installation

This repository is HACS-compatible as a custom integration. For the private
repository, make sure HACS has GitHub access to `MaxRink/astra-energy-ha`, then
add it as a custom repository:

```text
HACS -> Integrations -> Custom repositories
Repository: https://github.com/MaxRink/astra-energy-ha
Category: Integration
```

Install `Astra Energy`, restart Home Assistant, then add the integration from
Settings -> Devices & services. Alpha releases are tagged with
`v0.1.0-alpha.1` style versions.

### Manual Development Install

Copy or symlink `custom_components/astra_energy` into a Home Assistant config
directory, restart HA, then add the integration from the UI.

The current implementation authenticates through `csandroid.php` and creates
Energy Dashboard-compatible `kWh` sensors from the latest meter-reading endpoint
when Astra returns cumulative `kWh` rows.
If the configured mobile endpoint returns an invalid or empty response, the
client retries the known Android and iOS mobile endpoints before reporting the
update failure.

Historical import is available as the `astra_energy.backfill_history` action.
By default it only fetches and logs historical readings. Enable
`import_statistics` in the action or options to write compatible cumulative
`kWh` rows into recorder long-term statistics. The action can return a meter
row-count summary to Home Assistant service callers and creates repair issues
plus persistent notifications when API updates or statistics imports fail.
Set `history_granularity` to `quarter_hour` to import Astra's 15-minute
energy-balance rows; the default `monthly` mode uses the cheaper monthly meter
stands. Quarter-hour imports call one provider endpoint per day and can be slow;
set `run_in_background` for long backfills behind reverse proxies. Home
Assistant long-term statistics imports must use top-of-hour timestamps, so the
Energy Dashboard import stores hourly rows selected from the 15-minute source
data; the local CSV export tool keeps the full 15-minute resolution for
inspection.

Quarter-hour payloads are cached in Home Assistant storage after the first
successful fetch. Later imports reuse cached old days and only re-fetch the
recent overlap window, four days by default, so Astra is not hammered for
immutable history. The
importer also rejects impossible negative or spike values before writing
recorder statistics. Recorder imports also skip cumulative rollbacks and
implausible hourly jumps so a bad provider value cannot create negative
hundreds-of-kWh Energy Dashboard deltas. Delayed/bunched values are
redistributed over preceding flat intervals when possible, and impossible
residential-scale spikes are rejected. The unsmoothed diagnostic sensors remain
available as live entities only and are deliberately not imported into recorder
statistics, because they preserve raw provider anomalies for inspection. Enable debug logging for
`custom_components.astra_energy` to see API action timing, fetched-vs-cached day
counts, and anomaly repair counters.
Current live readings are subject to the same residential-scale guard. If Astra
or the browser sidecar only returns a large cumulative catch-up after an outage,
the integration keeps the cumulative Energy Dashboard sensors unavailable or at
their last safe value until a proper historical import can fill the missing
hours.

Quality-scale tracking is in `docs/quality-scale.md`.

## Removal

Remove the integration from Settings → Devices & services, then delete
`custom_components/astra_energy` and restart Home Assistant.

### Advanced Configuration Options

The following options can be configured during setup or via the integration options:

- **`poll_interval`**: How often to poll live data (seconds).
- **`backfill_days`**: Number of days to look back for historical data on startup.
- **`recent_refresh_hours`**: Hours of recent history to continuously refresh.
- **`history_granularity`**: Granularity of historical data (`quarter_hour`, `monthly`, etc).
- **`import_statistics`**: Whether to import historical data into HA's long-term statistics.
- **`grid_price_net`**: Net price per kWh for grid consumption.
- **`solar_price_net`**: Net price per kWh for solar/object consumption.
- **`tax_rate`**: Tax rate applied to net prices.
- **`max_interval_average_kw`**: Maximum expected average kW per interval (anomalies above this are smoothed).
- **`smooth_interval_anomalies`**: Enable/disable automatic smoothing of unrealistic spikes.
- **`anomaly_redistribution_window`**: Number of buckets to spread smoothed anomalies across.
- **`smoothing_lookaround_days`**: Number of days to use for estimating missing/smoothed intervals.
- **`cache_interval_payloads`**: Cache large interval payloads on disk for debugging.
- **`web_fallback_enabled`**: Use web session as fallback if API fails.
- **`web_base_url`**: Base URL for web fallback.
- **`web_session_id`** / **`web_cookie`**: Session/cookie for web fallback.
- **`browser_proxy_enabled`**: Use an external browser proxy sidecar for data retrieval.
- **`browser_proxy_url`** / **`browser_proxy_token`**: Endpoint and auth token for the browser proxy.
