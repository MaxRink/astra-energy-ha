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

Manual login can be completed through the exposed CDP port (`9222`) when Astra
shows reCAPTCHA or another interactive challenge.
