# Repository Instructions

This repository contains the `astra_energy` Home Assistant custom integration and
supporting Astra API analysis tools.

## Scope

These instructions apply to the whole repository.

## Development Rules

- Keep Home Assistant integration code under `custom_components/astra_energy`.
- Keep API exploration and one-off support tooling under `tools`.
- Add or update tests in `tests` for every parser, sanitizer, error-handling, or
  recorder/statistics behavior change.
- Do not commit real credentials, cookies, session IDs, raw dumps with personal
  data, or Home Assistant tokens. Use `.secrets.env` locally only.
- Treat screenshots as evidence only after visually inspecting them. Screenshots
  must show the actual Home Assistant UI or target app UI and the changed feature
  clearly.
- Prefer small targeted fixes with a regression test over broad rewrites.

## Validation

Run before committing or tagging:

```sh
python -m pytest
python -m ruff check .
```

If Home Assistant-specific validation is needed, use a disposable local HA
instance or the private test instance and document what was verified.
