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

Public App Store metadata also shows an iOS app, bundle
`de.astra-software.astracockpit`, version `1.3`. If the Android endpoint stops
returning data, obtain the IPA with Apple-authenticated tooling and repeat the
static string/API analysis against the iOS binary.

## Home Assistant Development

Copy or symlink `custom_components/astra_energy` into a Home Assistant config directory, restart HA, then add the integration from the UI.

The current implementation authenticates through `csandroid.php` and creates
Energy Dashboard-compatible `kWh` sensors from the latest meter-reading endpoint
when Astra returns cumulative `kWh` rows.

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
recent overlap window so Astra is not hammered for immutable history. The
importer also rejects impossible negative or spike values before writing
recorder statistics. Delayed/bunched values are redistributed over preceding
flat intervals when possible, and impossible residential-scale spikes are
rejected. Enable debug logging for `custom_components.astra_energy` to see API
action timing, fetched-vs-cached day counts, and anomaly repair counters.

Quality-scale tracking is in `docs/quality-scale.md`.

## Removal

Remove the integration from Settings → Devices & services, then delete
`custom_components/astra_energy` and restart Home Assistant.
