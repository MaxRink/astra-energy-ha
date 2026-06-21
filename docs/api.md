# Astra API Notes

## Confirmed Android API Surface

The Android app (`de.astra_software.astracockpit`) is a native client, not a
WebView wrapper. Static analysis of the installed APK found the primary API:

- `POST https://astra-cloud.com/readyxnet/source/login/csandroid.php`
- Content type: `application/x-www-form-urlencoded`
- Every request includes `s_dv=1`.
- Every response is `<payload><md5(payload)>`; the client must verify the last
  32 characters before parsing the payload.
- Local APK version analyzed: package `de.astra_software.astracockpit`,
  `versionName=1.0.14`, `versionCode=16`.

OpenAPI reference: [openapi-astra-android.yaml](openapi-astra-android.yaml).

### Request Signing

Each action is signed with a timestamp fetched from the same endpoint:

1. Fetch timestamp:
   - `s_action=get_ts`
   - `s_ts=`
   - `s_cs=md5("SNAFU" + "get_ts" + "")`
2. Fetch action:
   - `s_action=<action>`
   - `s_ts=<timestamp response>`
   - `s_cs=md5("SNAFU" + action + timestamp)`

Login/session id:

- `s_sid=md5(username + md5(password))`
- The app stores this value locally and reuses it for session restore.

### Common Parameters

- `s_sid`: Android session id.
- `s_immo`: selected location/property id, initially `-1`, then `immo_sel` from
  login. Observed IDs are hierarchical strings:
  - `3^...`: branch/site tree root.
  - `4^...`: building/project level. The active account selected `4^263`.
  - `5^...`: tenant/apartment level.
  - `-1`: section separators in `standort_list`.
- `s_year`: selected year.
- `s_med`: medium id; default `1`.
- `s_lang`: language, observed `de`.
- `s_mnt`: selected month, `-1` for default/all.
- `s_datum`: selected date, `-1` for default/all.

### Confirmed Actions

- `auth_login`: authenticate and return account metadata plus initial data.
- `get_verbrauch`: non-tenant consumption overview.
- `get_mtr_vb_overview`: tenant/meter consumption overview.
- `get_mtr_verbrauch`: meter consumption series.
- `get_mtr_vbmed`: consumption by medium, including 14h quarter-hour fields
  when `s_datum=YYYY-MM-DD`.
- `get_mtr_hist`: historical consumption card.
- `get_mtr_autarkie`: self-sufficiency/autarky card.
- `get_mtr_eb`: energy balance, including the best observed grid/PV 15-minute
  split when `s_datum=YYYY-MM-DD`.
- `get_mtr_lzs`: latest meter readings. This is the first Energy Dashboard
  source because it exposes reading values and units.
- `get_mtr_inv`: invoices.
- `get_mtr_inv_pdf`: invoice PDF metadata; called with `s_id`.
- `get_immo_list`: location/property list.
- `get_wf`: weather forecast.
- `lngchg_medium_list`: medium list after language change.

All Android data actions share the same `ServerDataTask` request body:
`s_sid`, `s_immo`, `s_year`, `s_med`, `s_lang`, `s_mnt`, and `s_datum`.
The only exception found in the APK is `get_mtr_inv_pdf`, which uses
`s_sid` and `s_id` and then opens
`https://astra-cloud.com/{alias}/readyxnet/source/userdocs/{pdfUri}`.

### JSON Fields Observed In App Parser

`auth_login`:

- Top-level: `auth`, `comp_id`, `comp_name`, `user`, `auft`, `immo_sel`,
  `is_mieter`, `is_t1t2`, `med_list`, `standort_list`.
- `med_list[]`: `id`, `name`, `img`.
- `standort_list[]`: `id`, `name`, `country`.
- Selected captures contain 447 `standort_list` entries: 1 root-like `3^...`
  entry, 2 building-level `4^...` entries, 438 tenant-level `5^...` entries,
  and 6 separator rows. This is useful for discovery but must not be polled
  blindly because it can enumerate other tenants under the same tree. Bounded
  non-selected `s_immo` probes stalled; keep this as documentation-only until a
  safe user-approved enumeration strategy exists.

`get_mtr_lzs`:

- Top-level: `auth`, `data`.
- `data[]`: `v01`, `v02`, `v03`, `v04`, `v05`, `v06`, `v07`.
- App semantics from parser: label, current meter value, unit, interval
  consumption, date, medium, account/order.
- Live data can contain one physical meter plus `T1` and `T2` channel rows. The
  integration groups those rows into one Home Assistant device:
  - physical/VGB row -> total cumulative energy and device identifier
  - `T1` / `Netzbezug` row -> grid cumulative energy
  - `T2` / `Objektbezug` / `PV` row -> solar/object cumulative energy

`get_mtr_vb_overview`:

- `data[]`: `v01`, `v02`, `v03`.
- App semantics from parser: label, numeric value, unit.

`get_mtr_verbrauch`:

- `data[0]`: `_vb_vll_vy`, `_vb_vll_ly`, `_vb_x`, `_vb_ttl`, `_vb_eh`.

`get_mtr_eb` daily 15-minute view:

- Request with `s_datum=YYYY-MM-DD`.
- `data[0]._lvb_lbl_14h`: 96 labels from `00:15` through next-day `00:00`.
- `data[0]._lvb_ttl`: `Gesamtbezug,Netzbezug,Objektbezug,PV-Bezug,Batterie-Bezug`.
- `data[0]._lvb_vll_14h`: semicolon-separated interval-kWh series matching
  `_lvb_ttl`. For one row, average kW is `interval_kWh * 4`.
- Observed 2026-06-19 totals from this endpoint: total 34.966 kWh, grid
  19.399199 kWh, solar/object 16.690709 kWh, battery 0 kWh.
- The 15-minute labels are provider-local `Europe/Berlin` interval-end labels,
  not UTC labels. The integration converts them to UTC before importing Home
  Assistant statistics.
- Observed 2026-06-21 selected-location payloads from both `get_mtr_eb` and
  `get_mtr_vbmed` contained non-zero rows only from `00:15` through `02:00`;
  all later quarter-hour rows were zero. Before the local-time fix this looked
  like a cutoff around 04:00 in Home Assistant. The missing later values are
  provider/API-side; the two-hour display shift was integration-side.
- The same payload exposes PV delivery/generation card series:
  - `_lez_ttl`: `PV-Gesamtlieferung,PV-Netzlieferung,Batterie-Ladung,PV-Objektlieferung`.
  - `_ez_ttl`: `PV-Netzlieferung,Batterie-Ladung,PV-Objektlieferung`.
  - `_vbt2r_ttl` and `_lt2rvb_ttl`: tariff split variants for
    `Netzbezug,Objektbezug` and `Gesamtbezug,Netzbezug,Objektbezug`.
- No local capture currently contains a confirmed `Gemeinstrom` /
  shared-electricity label. If the provider adds it, it should be treated as a
  separate channel only after the series semantics are verified against the UI.
  Current selected-location Android labels only expose
  `Gesamtbezug`, `Netzbezug`, `Objektbezug`, `PV-Bezug`, and
  `Batterie-Bezug`; web captures additionally show report links for meter IDs
  but no confirmed `Gemeinstrom` data row.

`get_verbrauch`:

- `vb_vy[]`, `vb_ly[]`, `vb_x[]` with `v01` through `v12`.
- `vb_leg[]`: `VJ`, `LJ`.
- `vb_eh`: unit.

`get_mtr_vbmed` daily 15-minute view:

- Request with `s_datum=YYYY-MM-DD`.
- The observed `_hvb_vll_14h` and `_hvbt2r_vll_14h` fields contained total
  quarter-hour consumption, but tariff split series were zero in this endpoint.
  Prefer `get_mtr_eb` for split grid/solar 15-minute analysis.

`get_mtr_hist` and `get_mtr_autarkie` return card-oriented JSON fields such as
labels, units, colors, and chart values. These are useful for dashboards but
should not be mapped to Energy Dashboard totals until their semantics are
validated live.

`get_wf`:

- Weather forecast/card endpoint used by the app.
- `data[0]` fields parsed by the APK: `_vll1` through `_vll6`, `_lbl6`,
  `_ttl1`, `_ttl1_1`, and `_ttl2` through `_ttl6`.

### Android Backend Recheck, 2026-06-21

The previously working Android endpoint currently returns HTTP 200 with an empty
body for `get_ts` before credentials are used. This was reproduced against both
`https://astra-cloud.com/readyxnet/source/login/csandroid.php` and
`https://astra-cloud.com/astra04/readyxnet/source/login/csandroid.php`.

App-like `User-Agent`, `Accept`, `Origin`, `Referer`, and explicit UTF-8 content
type headers did not change the empty response. Alternate simple timestamp
action/signature guesses also returned empty 200 responses. This suggests either
temporary backend behavior, IP/backend filtering, or a protocol change in a
newer mobile app. It is not evidence of bad credentials because the failure
happens at unauthenticated timestamp fetch.

Use this schema-only probe for bounded future checks:

```sh
python3 tools/astra_endpoint_discovery.py \
  --actions get_mtr_preis,get_gemeinstrom \
  --out captures/astra-endpoint-discovery-latest.json
```

## Confirmed iOS App Metadata

Public App Store metadata identifies an iOS app:

- App Store ID: `1516855287`
- Bundle ID: `de.astra-software.astracockpit`
- Version observed via Apple lookup: `1.3`
- Current version release date: `2026-03-26T07:54:00Z`
- Size: `2893824` bytes
- Languages: English and German
- Minimum OS: iOS 13.0
- App Store URL: `https://apps.apple.com/de/app/astra-cockpit/id1516855287`

The iOS app is newer than the locally analyzed Android APK. If the Android
`csandroid.php` endpoint keeps returning empty `get_ts`, the next best source of
truth is static and/or dynamic iOS app analysis:

1. Obtain the IPA through Apple-authenticated tooling such as `ipatool`, Apple
   Configurator, or a paired-device export.
2. Extract the IPA and run `strings` on the app binary for `astra-cloud.com`,
   `readyxnet`, `s_action`, `get_ts`, and endpoint/action names.
3. If static strings are insufficient, run the iOS app through an HTTPS proxy on
   a test device and capture only request URLs, form keys, and response schemas.
4. Keep IPA files and raw captures out of git.

## Local Testing

The protocol can be tested without Home Assistant:

```sh
python3 tools/astra_mobile_probe.py --username '<username>'
```

The probe asks for the password without echoing it, performs `auth_login`, then
fetches `get_mtr_lzs` by default and prints only metadata/schema counts.

Unit tests also run without Home Assistant installed:

```sh
python3 -m pytest -q
```

## Known Public Web Surface

- Base URL observed from the user-provided link: `https://astra-cloud.com/astra04/readyxnet`.
- Standalone login URL: `https://astra-cloud.com/readyxnet/source/login/csloginw.php`.
- Direct `source/pm/pm_customlogin.php` is not standalone; it checks
  `parent.navigation` and redirects to `../common/ErrorPage.php` when loaded
  without the expected frameset context.
- `source/pm/` returns an old HTML frameset and loads `login.php?sessionId=&LS=`
  into frame `PM_home`.
- The portal uses ISO-8859-1 HTML and PHP endpoints.
- The browser login uses reCAPTCHA and is therefore less suitable for unattended
  Home Assistant polling than the Android API.
- The browser login page loads reCAPTCHA v3 with sitekey
  `6LdWT-AZAAAAAA4XSFlDy4EL6k-TPw-ibrptnsy7`. The frontend JavaScript calls
  `grecaptcha.execute(..., {action: "login"})`, writes the returned token to
  `g-recaptcha-response`, sets `EULA_OK=1`, and submits `csloginw.php`.
- Direct login POST probes with the account credentials and missing, empty, or
  bogus `g-recaptcha-response` all returned the login page and did not include
  a session/bootstrap response. That means the web backend enforces a valid
  reCAPTCHA token; the field is not just cosmetic.
- FlareSolverr `3.5.0` at `http://192.168.1.104:31027/v1` fetched the login
  page and reported `Challenge not detected!`; it did not remove the reCAPTCHA
  requirement.
- Byparr `2.1.0` at `http://192.168.1.104:30230/v1` is reachable and can fetch
  simple pages, but returned HTTP 500 for the Astra login page in the observed
  probe. Its request schema is FlareSolverr-like but uses `max_timeout` seconds
  instead of `maxTimeout` milliseconds.
- Local retest helper:

  ```sh
  python3 tools/astra_web_login_probe.py \
    --flaresolverr-url http://192.168.1.104:31027/v1 \
    --byparr-url http://192.168.1.104:30230/v1
  ```

## Confirmed Web Endpoints

OpenAPI reference: [openapi-web-observed.yaml](openapi-web-observed.yaml).

- `POST /readyxnet/source/login/csloginw.php`: browser login form with
  `UserName`, `Password`, `Email`, `strRequestType=Submit`, and
  `g-recaptcha-response`.
- `POST /astra04/readyxnet/source/pm/pm_customlogin.php`: frame/bootstrap page
  after browser login.
- `POST /astra04/readyxnet/source/pm/ajax.php`: widget RPC endpoint using JSON
  request bodies.
- `GET /astra04/readyxnet/source/pm/pm_repeaverbr.php`: report page. Observed
  variants include `Report=2`, `Report=3`, and `Report=4`, with `s_year`,
  optional `s_fday`, optional `s_rmnt`, `s_eh`, `s_gtz`, and `MWSTENB`.
  The page contains a `Preis` column, but all observed variants had blank price
  cells; `MWSTENB=1` did not populate tariff values.
- `GET /astra04/readyxnet/source/pm/pm_repzw.php`: meter-reading page.
- `GET /astra04/readyxnet/source/pm/pm_prbzgww.php`: warning/limit settings.
- `GET /astra04/readyxnet/source/pm/pm_graph.php`: HTML graph/image-map page.
  The physical meter graph exposes 15-minute cumulative and interval kWh points
  in tooltip text. Direct T1/T2 graph IDs returned zero curves for the observed
  2026-06-19 daily range.
- `GET /astra04/readyxnet/source/pm/pm_repeavbenrvr.php`: linked from report
  pages; not yet semantically decoded.
- `GET /astra04/readyxnet/source/pm/pm_tddview.php`: linked from report pages;
  likely a detail/table view, not yet semantically decoded.
- `GET /astra04/readyxnet/source/pm/pm_zs3.php`: linked from report pages; not
  yet semantically decoded.
- `GET /astra04/readyxnet/source/pm/pm_prbzgwwadd.php`: linked from the warning
  settings page; likely an add/edit flow for warning limits.
- `GET /astra04/readyxnet/source/pm/pm_setper.php`, `pm_setvbint.php`,
  `pm_setvgper.php`, `pm_setatper.php`, and `pm_setcvis.php`: linked from graph
  pages; likely graph period/visibility preference endpoints.

Widget RPC methods observed:

- `PMCustomContent::LoadWidgetContents`
- `PMCustomContent::RefreshWidgetContentsNew`
- `PMCustomContent::CheckMessages`
- `PMCustomContent::isSessionAlive`
- `PMCustomContent::WGAddContent`

## Home Assistant Mapping Rules

- Current power should become a `W` sensor with `device_class=power` and
  `state_class=measurement`.
- Imported cumulative energy should become a `kWh` sensor with
  `device_class=energy` and `state_class=total_increasing`.
- If Astra exposes interval deltas but not a cumulative total, the integration
  must persist and synthesize a monotonic total before enabling it by default
  for the Energy Dashboard.
- Credentials, cookies, tokens, meter IDs, names, and raw consumption data must
  be redacted from diagnostics and committed docs.
- `get_mtr_lzs` is the preferred initial Energy Dashboard source. Group
  physical/T1/T2 `kWh` rows as one device and expose total, grid, and
  solar/object channels as `total_increasing`. Grid import is derived as
  `total - solar/object` when both channels exist; the observed Astra overview
  uses that relationship and raw T1 can disagree around meter replacement.
- `get_mtr_eb` with `s_datum=YYYY-MM-DD` exposes daily 15-minute energy-balance
  rows. The integration can backfill these as synthesized cumulative
  `total_increasing` statistics when `history_granularity` is set to
  `quarter_hour`; recorder import rows are aligned to top-of-hour timestamps
  because Home Assistant's long-term statistics import API rejects sub-hourly
  starts. The default remains `monthly` because quarter-hour import requires one
  slow API call per day. Use the action's `run_in_background` field for long
  imports.
- Do not expose Android card values (`_vb_vll`, `_lvb_vll`, `_ez_vll`, etc.) as
  Energy Dashboard totals until live values prove they are cumulative.
- Use the `recent_refresh_hours` option/service field to re-fetch a recent
  overlap window, default 24 hours, when importing historical statistics.
- Confirmed pricing data is currently limited to invoice totals from
  `get_mtr_inv`. Per-kWh grid/PV tariffs should only become Home Assistant price
  entities once an endpoint returns actual tariff values. When confirmed, expose
  gross values as `net_price * 1.19` because the provider values are before tax.

## Local Analysis Artifacts

- `tools/astra_15min_export.py`: converts a raw daily `get_mtr_eb` capture into
  a 96-row CSV and SVG graphs for interval kWh and average kW.
- `tools/astra_web_probe.py`: fetches observed web graph/report endpoints with a
  locally captured browser session and writes ignored CSV/SVG/report artifacts.
