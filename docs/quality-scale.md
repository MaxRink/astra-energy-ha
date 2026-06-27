# Home Assistant Quality Scale Status

Target: Platinum-compatible implementation patterns for a future Home Assistant
Core contribution. This custom integration cannot fully claim official Platinum
until it is reviewed in Home Assistant Core, has official brands assets, and has
Core test coverage in Home Assistant's test harness.

Rules are based on the current Home Assistant integration quality-scale
checklist.

## Bronze

- [x] `action-setup`: no setup-time actions outside `async_setup_entry`; native
  backfill action is registered on entry setup and removed on unload.
- [x] `appropriate-polling`: default polling is 3600 seconds and configurable
  from the UI.
- [ ] `brands`: needs an official Home Assistant brands PR.
- [x] `common-modules`: API, coordinator, statistics, entities, diagnostics, and
  discovery tooling are split into focused modules.
- [ ] `config-flow-test-coverage`: local protocol tests exist; full HA config
  flow tests need the Home Assistant test harness.
- [x] `config-flow`: setup, reauth, reconfigure, and auto-reloading options are
  UI based.
- [x] `dependency-transparency`: no external Python dependency is required by
  the integration; it uses Home Assistant's aiohttp session.
- [x] `docs-actions`: documented in README/API docs.
- [x] `docs-high-level-description`: documented.
- [x] `docs-installation-instructions`: documented for custom integration use.
- [x] `docs-removal-instructions`: documented in README.
- [x] `entity-event-setup`: coordinator listener is registered through entry
  unload cleanup.
- [x] `entity-unique-id`: sensor unique IDs are stable per Astra meter hash and
  sensor type.
- [x] `has-entity-name`: sensors expose explicit friendly names because this
  provider's raw meter serial is not user-friendly as the device name.
- [x] `runtime-data`: coordinator is stored in `ConfigEntry.runtime_data`.
- [x] `test-before-configure`: config flow validates credentials with the
  Android API before creating entries.
- [x] `test-before-setup`: first refresh validates setup.
- [x] `unique-config-entry`: username is used as config-flow unique ID.

## Silver

- [x] `action-exceptions`: backfill raises `HomeAssistantError` for recorder API
  availability and statistics import issues.
- [x] `config-entry-unloading`: platform unload and action removal are
  implemented.
- [x] `docs-configuration-parameters`: documented.
- [x] `docs-installation-parameters`: documented.
- [x] `entity-unavailable`: coordinator-backed entities become unavailable when
  updates fail.
- [x] `integration-owner`: manifest has a code owner placeholder.
- [x] `log-when-unavailable`: coordinator handles update errors through HA's
  standard `UpdateFailed` path and reports them through repair issues and
  persistent notifications.
- [ ] `parallel-updates`: acceptable for coordinator-only polling, but should be
  verified in HA test harness.
- [x] `reauthentication-flow`: implemented.
- [ ] `test-coverage`: local tests cover protocol helpers and parsing; >95%
  module coverage requires HA test harness and mocks.

## Gold

- [x] `devices`: one device is created per physical Astra meter; T1/T2 channel
  rows are grouped under that device.
- [x] `diagnostics`: implemented and redacts credentials/session-like fields.
- [ ] `discovery-update-info`: no local discovery mechanism exists for a cloud
  account service.
- [ ] `discovery`: not applicable unless Astra publishes discovery metadata.
- [x] `docs-data-update`: documented.
- [x] `docs-examples`: action/backfill example documented.
- [x] `docs-known-limitations`: documented.
- [x] `docs-supported-devices`: documented as Astra Cockpit account meters.
- [x] `docs-supported-functions`: documented.
- [x] `docs-troubleshooting`: documented.
- [x] `docs-use-cases`: documented.
- [x] `dynamic-devices`: new meters are added when coordinator data changes.
- [x] `entity-category`: coordinator status entities are marked diagnostic.
- [x] `entity-device-class`: energy and power classes are assigned where
  possible.
- [x] `entity-disabled-by-default`: exported energy and live power are disabled
  by default until Astra exposes those channels for the account.
- [x] `entity-translations`: entity names are translated.
- [x] `exception-translations`: config-flow errors are translated.
- [ ] `icon-translations`: not needed for device-class sensors, but can be added
  if custom icons are introduced.
- [x] `reconfiguration-flow`: implemented.
- [x] `repair-issues`: API auth, API availability, and backfill failures create
  Home Assistant repair issues with translated messages.
- [ ] `stale-devices`: not implemented yet; needs policy for removed Astra
  meters after live testing.

## Platinum

- [x] `async-dependency`: API client is fully async.
- [x] `inject-websession`: Home Assistant's aiohttp web session is injected into
  the client.
- [ ] `strict-typing`: code is typed, but strict mypy/pyright validation has not
  been run in Home Assistant Core.
