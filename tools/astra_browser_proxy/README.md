# Astra Browser Proxy

This sidecar keeps a persistent logged-in Astra browser profile and exposes a
small local JSON API for the Home Assistant integration. It is only a fallback
for cases where the mobile Astra API returns empty or checksum-invalid payloads.

## Endpoints

- `GET /health`: redaction-safe status and browser/profile availability.
- `GET /current`: current meter values parsed from the Astra web dashboard
  widget.
- `POST /login`: opens or refreshes the persistent browser context and tries a
  best-effort credential login if `ASTRA_USERNAME` and `ASTRA_PASSWORD` are set.

If `ASTRA_SHARED_TOKEN` is set, requests must send
`Authorization: Bearer <token>`.

## Deployment

Use the example compose file as a template and store real secrets outside git.
The profile volume must persist across restarts so cookies/local storage survive.

```sh
docker compose up -d --build
```

The current Astra Cockpit login page uses `#UserName`, `#Password` and an
`input[type=image]` submit control. The sidecar now fills those fields and
clicks the image control; older versions filled the form but never submitted
it. The page also hides an `Email` input and requires a reCAPTCHA v3 token, so
an interactive login through the exposed CDP port (`9222`) is still required
when Astra challenges the browser.

The mobile API and the web portal are separate login paths. A working mobile
login does not create a web session, and an expired web session does not
invalidate the mobile credentials. If the mobile endpoint returns an empty
HTTP 200, check the provider's IP/rate limiting before rotating the password;
the same credentials can work from another egress IP.
