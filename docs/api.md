# Astra API Notes

## Confirmed Android API Surface

The Android app (`de.astra_software.astracockpit`) is a native client, not a
WebView wrapper. Static analysis of the installed APK found the primary API:

- `POST https://astra-cloud.com/readyxnet/source/login/csandroid.php`
- Content type: `application/x-www-form-urlencoded`
- Every request includes `s_dv=1`.
- Every response is `<payload><md5(payload)>`; the client must verify the last
  32 characters before parsing the payload.

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
  login.
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
- `get_mtr_vbmed`: consumption by medium.
- `get_mtr_hist`: historical consumption card.
- `get_mtr_autarkie`: self-sufficiency/autarky card.
- `get_mtr_eb`: energy balance.
- `get_mtr_lzs`: latest meter readings. This is the first Energy Dashboard
  source because it exposes reading values and units.
- `get_mtr_inv`: invoices.
- `get_mtr_inv_pdf`: invoice PDF metadata; called with `s_id`.
- `get_immo_list`: location/property list.
- `get_wf`: weather forecast.
- `lngchg_medium_list`: medium list after language change.

### JSON Fields Observed In App Parser

`auth_login`:

- Top-level: `auth`, `comp_id`, `comp_name`, `user`, `auft`, `immo_sel`,
  `is_mieter`, `is_t1t2`, `med_list`, `standort_list`.
- `med_list[]`: `id`, `name`, `img`.
- `standort_list[]`: `id`, `name`, `country`.

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

`get_verbrauch`:

- `vb_vy[]`, `vb_ly[]`, `vb_x[]` with `v01` through `v12`.
- `vb_leg[]`: `VJ`, `LJ`.
- `vb_eh`: unit.

`get_mtr_eb`, `get_mtr_vbmed`, `get_mtr_hist`, and `get_mtr_autarkie` return
card-oriented JSON fields such as `_vb_vll`, `_lvb_vll`, `_ez_vll`, labels,
units, colors, and 14h variants. These are useful for dashboards but should not
be mapped to Energy Dashboard totals until their semantics are validated live.

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
  optional `s_fday`, and optional `s_rmnt`.
- `GET /astra04/readyxnet/source/pm/pm_repzw.php`: meter-reading page.
- `GET /astra04/readyxnet/source/pm/pm_prbzgww.php`: warning/limit settings.

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
  solar/object channels as `total_increasing`.
- Do not expose Android card values (`_vb_vll`, `_lvb_vll`, `_ez_vll`, etc.) as
  Energy Dashboard totals until live values prove they are cumulative.
