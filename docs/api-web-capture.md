# Astra Web Capture Summary

Source capture: `captures/web-login.jsonl`

Sensitive values are redacted. Raw captures stay local and are gitignored.

## Endpoints

### `GET https://astra-cloud.com/astra04/readyxnet/source/pm/`

- Seen: `1` time(s)
- Statuses: `200`
- MIME types: `text/html`
- Query: none
- Request body kind: `none observed`
- Request body summary: none
- Response body hints: `{"body_bytes": 1566, "linked_php_js": ["login.php?sessionId=&LS="]}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `GET https://astra-cloud.com/astra04/readyxnet/source/pm/login.php`

- Seen: `1` time(s)
- Statuses: `200`
- MIME types: `text/html`
- Query: none
- Request body kind: `none observed`
- Request body summary: none
- Response body hints: `{"body_bytes": 308, "linked_php_js": ["../common/ErrorPage.php?linkFlag=No&ErrorMessage=&sessionId=<redacted>"]}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `GET https://astra-cloud.com/astra04/readyxnet/source/pm/pm_customlogin.php`

- Seen: `2` time(s)
- Statuses: `200`
- MIME types: `text/html`
- Query: none
- Request body kind: `none observed`
- Request body summary: none
- Response body hints: `{"body_bytes": 303, "linked_php_js": ["../common/ErrorPage.php?linkFlag=No&ErrorMessage=&sessionId=<redacted>"]}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `GET https://astra-cloud.com/astra04/readyxnet/source/pm/pm_help.js`

- Seen: `2` time(s)
- Statuses: `200`
- MIME types: `text/javascript`
- Query: none
- Request body kind: `none observed`
- Request body summary: none
- Response body hints: `{"body_bytes": 223}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `GET https://astra-cloud.com/astra04/readyxnet/source/pm/pm_prbzgww.js`

- Seen: `1` time(s)
- Statuses: `200`
- MIME types: `text/javascript`
- Query: none
- Request body kind: `none observed`
- Request body summary: none
- Response body hints: `{"body_bytes": 10703, "text_hints": ["Warnwert", "Grenzwert"]}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `GET https://astra-cloud.com/astra04/readyxnet/source/pm/pm_prbzgww.php`

- Seen: `1` time(s)
- Statuses: `200`
- MIME types: `text/html`
- Query: `{"C_USER": "<redacted>", "Report": "2", "hID": "<redacted-id>", "id": "<redacted-id>", "prnr": "<redacted-id>", "s_back": "4", "s_year": "2026", "sessionId": "<redacted>"}`
- Request body kind: `none observed`
- Request body summary: none
- Response body hints: `{"body_bytes": 15415, "linked_php_js": ["pm_help.js", "pm_prbzgww.js"], "text_hints": ["Verbrauch", "kWh", "Warnwert", "Grenzwert"]}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `GET https://astra-cloud.com/astra04/readyxnet/source/pm/pm_repeaverbr.php`

- Seen: `7` time(s)
- Statuses: `200`
- MIME types: `text/html`
- Query: `{"C_IMMOID": "<redacted>", "C_USER": "<redacted>", "Report": "4", "prnr": "<redacted-id>", "prnr1": "<redacted-id>", "s_fday": "06", "s_gtz": "0", "s_year": "2026", "sessionId": "<redacted>"}`
- Request body kind: `none observed`
- Request body summary: none
- Response body hints: `{"body_bytes": 43960, "text_hints": ["Geraet", "kWh"]}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `GET https://astra-cloud.com/astra04/readyxnet/source/pm/pm_repzw.php`

- Seen: `1` time(s)
- Statuses: `200`
- MIME types: `text/html`
- Query: `{"prnr1": "<redacted-id>", "sessionId": "<redacted>"}`
- Request body kind: `none observed`
- Request body summary: none
- Response body hints: `{"body_bytes": 6064, "linked_php_js": ["pm_help.js", "pm_zw.js"], "text_hints": ["Zählerstand"]}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `GET https://astra-cloud.com/astra04/readyxnet/source/pm/pm_zw.js`

- Seen: `1` time(s)
- Statuses: `200`
- MIME types: `text/javascript`
- Query: none
- Request body kind: `none observed`
- Request body summary: none
- Response body hints: `{"body_bytes": 3213}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `GET https://astra-cloud.com/astra04/readyxnet/source/pm/wgmvba_chgdate.js`

- Seen: `2` time(s)
- Statuses: `200`
- MIME types: `text/javascript`
- Query: none
- Request body kind: `none observed`
- Request body summary: none
- Response body hints: `{"body_bytes": 9661}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `GET https://astra-cloud.com/astra04/readyxnet/source/pm/wgmvbb_chgdate.js`

- Seen: `2` time(s)
- Statuses: `200`
- MIME types: `text/javascript`
- Query: none
- Request body kind: `none observed`
- Request body summary: none
- Response body hints: `{"body_bytes": 9661}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `GET https://astra-cloud.com/astra04/readyxnet/source/pm/wgmvbmed_chgdate.js`

- Seen: `2` time(s)
- Statuses: `200`
- MIME types: `text/javascript`
- Query: none
- Request body kind: `none observed`
- Request body summary: none
- Response body hints: `{"body_bytes": 9753}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `GET https://astra-cloud.com/astra04/readyxnet/source/pm/wgmvbo_chgdate.js`

- Seen: `2` time(s)
- Statuses: `200`
- MIME types: `text/javascript`
- Query: none
- Request body kind: `none observed`
- Request body summary: none
- Response body hints: `{"body_bytes": 9661}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `GET https://astra-cloud.com/astra04/readyxnet/source/pm/wgreplastzs_chgdate.js`

- Seen: `2` time(s)
- Statuses: `200`
- MIME types: `text/javascript`
- Query: none
- Request body kind: `none observed`
- Request body summary: none
- Response body hints: `{"body_bytes": 9776}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `GET https://astra-cloud.com/readyxnet/source/login/csloginw.php`

- Seen: `1` time(s)
- Statuses: `200`
- MIME types: `text/html`
- Query: none
- Request body kind: `none observed`
- Request body summary: none
- Response body hints: `{"body_bytes": 4818, "linked_php_js": ["eula_de.php", "https://www.google.com/recaptcha/api.js?hl=de&render=6LdWT-AZAAAAAA4XSFlDy4EL6k-TPw-ibrptnsy7", "login.js?v=1.6", "pwdreset.php"]}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `GET https://astra-cloud.com/readyxnet/source/login/login.js`

- Seen: `2` time(s)
- Statuses: `200`
- MIME types: `application/javascript`
- Query: `{"v": "1.6"}`
- Request body kind: `none observed`
- Request body summary: none
- Response body hints: `{"body_bytes": 4480}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `POST https://astra-cloud.com/astra04/readyxnet/source/pm/ajax.php`

- Seen: `91` time(s)
- Statuses: `200`
- MIME types: `text/html`
- Query: `{"t": "1781988170490"}`
- Request body kind: `json`
- Request body summary: `{"json_keys": ["id", "method", "params"], "param_keys": ["sessionId", "url", "userId"], "params": {"sessionId": "<redacted>", "url": "pm_repzw.php?sessionId=<redacted>&prnr1=<redacted-id>", "userId": "<redacted>"}, "rpc_method": "PMCustomContent::isSessionAlive"}`
- Response body hints: `{"body_bytes": 60, "response_content_items": 1, "response_content_schema": ["keys=['content']"], "response_json_keys": ["id", "result"]}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `POST https://astra-cloud.com/astra04/readyxnet/source/pm/pm_customlogin.php`

- Seen: `2` time(s)
- Statuses: `200`
- MIME types: `text/html`
- Query: none
- Request body kind: `form`
- Request body summary: `{"form": {"s_stat": "1", "s_ver": "3", "sessionId": "<redacted>"}, "form_keys": ["s_stat", "s_ver", "sessionId"]}`
- Response body hints: `{"body_bytes": 61724, "linked_php_js": ["../../javascript/customlogin.js?v=1.0.4", "../../javascript/i18n/jquery.ui.datepicker-de.js", "../../javascript/jquery-3.1.1.js", "../../javascript/jquery-ui.js", "../../javascript/jquery.contextMenu-3.1.1.js"], "text_hints": ["Verbrauch", "Rechnung"]}`
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

### `POST https://astra-cloud.com/readyxnet/source/login/csloginw.php`

- Seen: `2` time(s)
- Statuses: `200`
- MIME types: `text/html`
- Query: none
- Request body kind: `form`
- Request body summary: `{"form": {"EULA_OK": "0", "Email": "<redacted>", "Password": "<redacted>", "UserName": "<redacted>", "bActivationFlag": "NOCHECK", "g-recaptcha-response": "<redacted>", "iCounter": "0", "strRequestType": "Submit", "userEULA": ""}, "form_keys": ["EULA_OK", "Email", "Password", "UserName", "bActivationFlag", "g-recaptcha-response", "iCounter", "strRequestType", "userEULA"]}`
- Response body hints: none
- Auth/session: inspect raw capture locally; sensitive headers are redacted here.

## AJAX RPC Methods

### `PMCustomContent::CheckMessages`

- Seen: `4` time(s)
- Sample params: `{"sessionId": "<redacted>", "userId": "<redacted>"}`

### `PMCustomContent::LoadWidgetContents`

- Seen: `14` time(s)
- Sample params: `{"sessionId": "<redacted>", "url": "wg_rechn.php?sessionId=<redacted>&s_wgid=55", "userId": "<redacted>", "wgid": "p_55"}`

### `PMCustomContent::RefreshWidgetContentsNew`

- Seen: `68` time(s)
- Sample params: `{"sessionId": "<redacted>", "url": "REFRESH=49567", "userId": "<redacted>", "wgid": "p_45"}`

### `PMCustomContent::WGAddContent`

- Seen: `1` time(s)
- Sample params: `{"min": "p_-1", "sessionId": "<redacted>", "state": "p_1,p_44,p_6,|p_55,p_46|p_45,p_47", "userId": "<redacted>"}`

### `PMCustomContent::isSessionAlive`

- Seen: `4` time(s)
- Sample params: `{"sessionId": "<redacted>", "url": "pm_repzw.php?sessionId=<redacted>&prnr1=<redacted-id>", "userId": "<redacted>"}`

## Report Variants

- `{"Report": "3", "body_hints": ["Geraet", "Verbrauch", "kWh", "Warnwert", "Grenzwert"], "s_fday": null, "s_rmnt": null, "s_year": "2026"}`
- `{"Report": "3", "body_hints": ["Geraet", "Verbrauch", "kWh", "Warnwert", "Grenzwert"], "s_fday": null, "s_rmnt": "6", "s_year": "2026"}`
- `{"Report": "3", "body_hints": ["Geraet", "Verbrauch", "kWh", "Warnwert", "Grenzwert"], "s_fday": null, "s_rmnt": "5", "s_year": "2026"}`
- `{"Report": "2", "body_hints": ["Geraet", "kWh"], "s_fday": "01", "s_rmnt": null, "s_year": "2026"}`
- `{"Report": "2", "body_hints": ["Geraet", "kWh"], "s_fday": "01", "s_rmnt": null, "s_year": "2026"}`
- `{"Report": "2", "body_hints": ["Geraet", "kWh"], "s_fday": "16", "s_rmnt": null, "s_year": "2026"}`
- `{"Report": "4", "body_hints": ["Geraet", "kWh"], "s_fday": "06", "s_rmnt": null, "s_year": "2026"}`

## Linked Hidden PHP/JS References

- `../../javascript/customlogin.js?v=1.0.4`
- `../../javascript/i18n/jquery.ui.datepicker-de.js`
- `../../javascript/jquery-3.1.1.js`
- `../../javascript/jquery-ui.js`
- `../../javascript/jquery.contextMenu-3.1.1.js`
- `../common/ErrorPage.php?linkFlag=No&ErrorMessage=&sessionId=<redacted>`
- `eula_de.php`
- `https://www.google.com/recaptcha/api.js?hl=de&render=6LdWT-AZAAAAAA4XSFlDy4EL6k-TPw-ibrptnsy7`
- `https://www.gstatic.com/recaptcha/releases/MerVUtRoajKEbP7pLiGXkL28/recaptcha__de.js`
- `login.js?v=1.6`
- `login.php?sessionId=&LS=`
- `pm_help.js`
- `pm_prbzgww.js`
- `pm_prbzgww.php?sessionId=<redacted>&s_prod=&id=<redacted-id>&hID=<redacted-id>&s_back=4&Report=2&s_year=2026&prnr=<redacted-id>&C_USER=<redacted>`
- `pm_prbzgww.php?sessionId=<redacted>&s_prod=&id=<redacted-id>&hID=<redacted-id>&s_back=4&Report=3&s_year=2026&prnr=<redacted-id>&C_USER=<redacted>`
- `pm_zw.js`
- `pwdreset.php`

## WebSocket Frames

- Captured WebSocket frame events: `0`

## Follow-up

- Promote confirmed endpoint schemas into `docs/api.md`.
- Do not commit the raw capture.
