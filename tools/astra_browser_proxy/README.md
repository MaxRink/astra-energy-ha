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
`input[type=image]` submit control. The sidecar fills those fields, clicks the
image control, and then waits up to 20 seconds for the asynchronous reCAPTCHA
callback to navigate to `pm_customlogin.php?sessionId=...` before capturing
cookies. Older versions filled the form but never submitted it, or captured the
session too early and reported a false negative.

In the 2026-11-01 browser tests, Playwright Chromium (headless) and headed
Chrome both posted a valid-length reCAPTCHA v3 token but received the login page
again. The CloakBrowser sidecar logged in successfully, captured the session,
and returned current meter data. That makes CloakBrowser the working automated
web-login path, while standard Chrome/Playwright remains unreliable for this
portal. The sidecar still supports interactive login through the exposed CDP
port (`9222`) when Astra challenges the browser.

This is an optional fallback. Use it only with your own account and in line
with the provider's terms. The mobile API remains the primary data path; a
working mobile login does not create a web session, and an expired web session
does not invalidate the mobile credentials. If the mobile endpoint returns an
empty HTTP 200, check the provider's IP/rate limiting before rotating the
password; the same credentials can work from another egress IP.
