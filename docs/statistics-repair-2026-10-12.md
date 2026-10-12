# Astra statistics repair receipt

Date: 2026-10-12

Home Assistant's supported recorder WebSocket API was used to repair cumulative
statistics after the Astra browser fallback published cached older meter stands.
No recorder database files were edited and no source readings were fabricated.

## Scope and evidence

- The native statistics query covered 1,244 to 1,245 hourly rows per channel,
  from 2026-06-14 through 2026-10-12.
- The returned range is sparse; missing hours were retained as missing.
- Three channels were checked: grid energy, solar energy, and total energy.
- The pre-repair export, correction ledger, and correction plan were written to
  protected local files with mode 0600. They are not repository artifacts.
- The correction plan fingerprint was
  `192730e3c0d2008e5f659b278daf0b22fada739126a4ae0d111185bdcb680175`.

## Applied changes

Twenty-three native `recorder/adjust_sum_statistics` operations succeeded. They
remove documented reset/rebound rows caused by the cached browser fallback and
preserve the positive increments surrounding each reset. A second verification
query found no remaining same-day rebound spikes. The remaining negative rows
are at the beginning of long gaps and were deliberately left untouched because
their missing source interval cannot be assigned to a specific day safely.

The corrected daily results are observed recorder increments, not proof that a
day with no recorded increment had zero physical consumption. Historical
grid/solar/total channel differences remain where the original provider
interval payload is unavailable; they were not rewritten by inference.

## Runtime protection

Alpha.59 prevents a cached browser fallback reading from replacing a newer
in-memory cumulative reading. The change is covered by the local test suite and
is deployed through Home Assistant's native update entity. Provider empty-HTML
responses and browser-proxy failures remain visible as deferred diagnostics; the
integration serves recorder fallback values until a fresh provider response is
available.
