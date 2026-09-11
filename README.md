# Quartermaster

Quartermaster is a credential-neutral quota evidence viewer and deterministic assignment adviser. It combines multi-account Claude evidence from [cswap](https://github.com/realiti4/claude-swap) with non-Claude provider evidence from [quota-axi](https://github.com/kunchenguid/quota-axi), without reading credentials, refreshing sessions, switching accounts, or launching agents.

It provides one agent-readable JSON contract, a compact curses/plain-text display, and a one-host request ledger that prevents concurrent callers from receiving the same unrecorded green reservation.

## Install

Python 3.11 or newer and `uv` are required.

```sh
uv tool install git+https://github.com/goblinmode2700/quartermaster.git
quartermaster --help
```

For a local wheel:

```sh
uv build
uv tool install --force dist/quartermaster_quota-0.1.0-py3-none-any.whl
```

State defaults to `~/.local/state/quartermaster`. Override it with `--state-dir` or `QUARTERMASTER_STATE_DIR`.

## Evidence boundary

Quartermaster reads JSON produced by cswap and quota-axi. Collection runs separately. Ordinary `cswap list --json` may refresh credentials, resynchronize backups, or perform migrations; check its behavior before adding it to an automated collection hook.

Supported source contracts:

- cswap v0.26.0, JSON schema v1 (`cswap list --json`)
- quota-axi 0.1.41 at commit `a19268827220e12e173067d11703e6ee36d5d88f`, JSON schema v5, with Claude excluded

A non-Claude collection example is:

```sh
quota-axi --provider codex,cursor,copilot,grok,kimi,zai,agy,alibaba,opencode-go \
  --no-credential-refresh --json \
  | quartermaster ingest quota-axi --host host-a
```

To import an existing cswap JSON document:

```sh
quartermaster ingest cswap --host host-a < cswap.json
```

Malformed input is rejected before the state lock is acquired and never replaces the last good snapshot. Each source/host snapshot is replaced independently, so concurrent ingestion preserves other providers and the request ledger.

## Commands

```sh
quartermaster ingest cswap [--file FILE] [--host HOST]
quartermaster ingest quota-axi [--file FILE] [--host HOST]
quartermaster status --json
quartermaster status
quartermaster tui [--once]
quartermaster advise --request-id REQ --provider claude \
  --metadata-json '{"demandEvidence":true}'
quartermaster reconcile REQ launch --process-id launcher:123
quartermaster reconcile REQ complete
quartermaster reconcile REQ cancel
```

`status` and `tui` only read local state. TUI redraws do not collect provider data. Non-TTY `tui` automatically renders one plain-text frame.

At 32 columns by 6 rows, two Claude accounts remain visible together. Smaller panes retain account rows where possible, mark hidden counts, and emit an explicit minimum-size message when unusable. `!`, `stale`, and `unknown` remain meaningful without color.

## Advice contract

Advice is arithmetic, advisory, and deterministic:

1. Source-reported exhaustion is `RED`.
2. Missing or stale current evidence is `UNKNOWN`.
3. Headroom at or below the configurable reserve (10 percentage points by default) is `YELLOW`.
4. Fresh windows above reserve are still `YELLOW` when demand evidence is missing or that account already has unresolved green demand.
5. `GREEN` requires fresh relevant windows, intact reserve, demand evidence, and an unreserved eligible account.

The ledger uses one stable `flock` with bounded wait, re-reads state under the lock, deduplicates request IDs by content, computes against pending/active demand, and atomically persists the decision before returning it. Contention exits 75 with `BUSY`. A lost reply can be retried with the same request ID. Reusing an ID with changed content fails. A launch changes pending demand to active; it does not release it. Time alone never releases a reservation. Cancellation or completion is explicit.

This first release intentionally does not predict task token cost, promise completion before reset, coordinate multiple hosts, merge provider identities without explicit evidence, switch accounts, kill tasks, or block launches. Existing runtime launch records are the future process/account binding hook.

## Synthetic check

```sh
tmp="$(mktemp -d)"
quartermaster --state-dir "$tmp" ingest cswap --host fixture --file tests/fixtures/cswap.json
quartermaster --state-dir "$tmp" status --json
quartermaster --state-dir "$tmp" tui --once
quartermaster --state-dir "$tmp" advise --request-id demo --provider claude \
  --metadata-json '{"demandEvidence":true}'
```

Fixtures use reserved `.invalid` identities and future timestamps; they contain no real accounts or tokens.

## Validation and integration status

The repository test suite covers schema rejection, atomic last-good preservation, independent source updates, two-account identity, stale/unknown states, weekly exhaustion, request replay/content mismatch, concurrent reservations, reconciliation, and 32×6/tiny rendering. CI runs lint, tests, and wheel builds on Python 3.11–3.13.

Synthetic tests do not verify a live installation. Before use:

- Check the installed cswap version and recovery procedure.
- Verify account labels and independent quota windows.
- Check the display at the intended terminal size, including resize and exit.
- Verify the consumer can read the installed `quartermaster status --json` output.

Rollback is `uv tool uninstall quartermaster-quota` (or reinstall a prior tag). Removing Quartermaster does not alter either upstream credential store. Preserve the state directory if pending ledger reconciliation is still needed.

## Development

```sh
uv sync --all-groups
uv run ruff check .
uv run pytest
uv build
```

See [docs/prior-art.md](docs/prior-art.md) for the adopt/port/reject decision.

## License

MIT. Quartermaster copies no upstream source code.
