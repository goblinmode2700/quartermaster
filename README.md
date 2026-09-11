# Quartermaster

Quartermaster is a credential-neutral quota evidence viewer and deterministic assignment adviser. It combines multi-account Claude evidence from [cswap](https://github.com/realiti4/claude-swap) with non-Claude provider evidence from [quota-axi](https://github.com/kunchenguid/quota-axi), without reading credentials, refreshing sessions, switching accounts, or launching agents.

It provides one agent-readable JSON contract, a rotating account-card display with an optional compact layout, and a one-host request ledger that prevents concurrent callers from receiving the same unrecorded green reservation.

## Install

Python 3.11 or newer and `uv` are required.

```sh
uv tool install git+https://github.com/goblinmode2700/quartermaster.git
quartermaster --help
```

For a local wheel:

```sh
uv build
uv tool install --force dist/quartermaster_quota-0.2.0-py3-none-any.whl
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

Malformed input is rejected before the state lock is acquired and never replaces the last good snapshot. Each source/host snapshot is replaced independently, retaining one prior normalized sample for rate evidence, so concurrent ingestion preserves other providers and the request ledger.

## Commands

```sh
quartermaster ingest cswap [--file FILE] [--host HOST]
quartermaster ingest quota-axi [--file FILE] [--host HOST]
quartermaster status --json
quartermaster status
quartermaster tui [--once]
quartermaster tui --rotate 5
quartermaster tui --rotate 0
quartermaster tui --compact
quartermaster view 2
quartermaster view label:2
quartermaster view auto
quartermaster advise --request-id REQ --provider claude \
  --metadata-json '{"demandEvidence":true}'
quartermaster reconcile REQ launch --process-id launcher:123
quartermaster reconcile REQ complete
quartermaster reconcile REQ cancel
```

`status` and `tui` only read local state. TUI redraws do not collect provider data. Non-TTY `tui` automatically renders one frame.

### Rotating display

Interactive `tui` shows one account at a time in bright white on black. A 44×9 pane fits a two-row headroom bar, three-row block digits, the limiting window, its reset countdown, and the account position. All ingested accounts participate. The default five-second interval completes a pass through ten accounts in 50 seconds, or eleven in 55 seconds. `--rotate SECONDS` changes the interval; `--rotate 0` holds.

Interactive TUI mode requires a UTF-8 locale and terminal color support. Quartermaster uses the current locale when possible, tries common UTF-8 fallbacks, and exits with an actionable error if either requirement is unavailable. `tui --once` remains available for noninteractive output and does not change terminal colors.

Keys `1`–`9` select the corresponding account; `0` selects account ten. Space or Right advances; Left goes back. Manual selection holds until `r` resumes rotation. With `--rotate 0`, automatic advancement remains disabled. `q` and Escape exit. Larger fleets remain reachable through navigation or the `view` command.

`quartermaster view SELECTOR` holds a card by its one-based position in `status --json`, full account identity, or unique label. Ambiguous selectors are rejected. Use `index:`, `identity:`, or `label:` when selector forms overlap; these prefixes also select numeric identities, numeric labels, or the label `auto`. `quartermaster view auto` resumes rotation. The command writes only a `view` entry under the existing state lock and preserves quota snapshots and requests. The TUI reads new selections on its next refresh; `--refresh` defaults to five seconds. Each selection has a revision, so a repeated agent command can override a later keyboard selection. Keyboard choices affect only that display process. Restarting a display reapplies the saved selection.

Selected identities remain selected if account order changes. If a held account disappears, the display says it is unavailable. Resume rotation or select another account to continue.

The bar and digits show the lowest remaining percentage among reported limiting windows; the countdown belongs to that same window. Values are rounded down to whole percentages. Numeric output in rotating cards, compact mode, and plain `status` requires timezone-aware measurement and reset timestamps; `Z` and explicit offsets are accepted. An omitted, null, malformed, timezone-naive, or expired reset shows `UNKNOWN RESET` and `?` instead of headroom.

For quota-axi, the known scopes must cover every reported window. Each scope's effective percentage must equal the minimum of its referenced windows, and its limiting-window identifiers must exactly identify every referenced window tied at that minimum. Unknown or conflicting scopes, unresolved bounds, duplicate identifiers, incomplete window coverage, and inconsistent limiter metadata show `UNKNOWN BOUNDS` and `?`. Other stale, unavailable, or missing evidence also fails closed. The display does not estimate how many tasks an account can finish.

Below nine rows the selected account uses a compact text card. Below 20×3 the display reports the minimum size. Without `--compact`, `tui --once` prints one card and exits; it does not rotate or change terminal colors.

### Compact display

Use `tui --compact` for the multi-account layout. Two Claude accounts remain visible together. Smaller panes mark hidden counts and emit a minimum-size message when unusable. `status` prints a static overview. `!`, `stale`, and `unknown` remain meaningful without color.

Account labels use the available terminal width, while quota and reset columns remain aligned even when reset clocks exceed five characters. Labels that exceed the available space end in `~`. The freshness marker is separated from the label by a space.

Control characters that can alter terminal layout are replaced with `?` before rendering; stored evidence is unchanged.

## Advice contract

Advice is arithmetic, advisory, and deterministic:

1. Source-reported exhaustion is `RED`.
2. Missing or stale current evidence is `UNKNOWN`.
3. Headroom at or below the configurable reserve (10 percentage points by default) is `YELLOW`.
4. Fresh windows above reserve are still `YELLOW` when demand evidence is missing or that account already has unresolved green demand.
5. `GREEN` requires fresh relevant windows, intact reserve, demand evidence, and an unreserved eligible account.

Rate evidence uses two source measurements for the same account identity. Their measurement timestamps must differ. For each window, the scope and reset timestamp must match. Both percentages must be present, and the remaining percentage must not increase. Quartermaster omits an invalid window and reports unknown rate evidence if no valid window remains. Unknown rate evidence does not cause an `UNKNOWN` advice decision.

The projection starts at the current source measurement and ends at the window reset. It does not start at the later advice time. Advice is `YELLOW` if a projection reaches or crosses the reserve. The advice result includes a `rateEvidence` object. For a selected account, this object records the interval and valid window projections. Display redraws do not create rate samples.

The ledger uses one stable `flock` with bounded wait, re-reads state under the lock, deduplicates request IDs by content, computes against pending/active demand, and atomically persists the decision before returning it. Contention exits 75 with `BUSY`. A lost reply can be retried with the same request ID. Reusing an ID with changed content fails. A launch changes pending demand to active; it does not release it. Time alone never releases a reservation. Cancellation or completion is explicit.

Quartermaster does not predict task token cost, promise completion before reset, coordinate multiple hosts, merge provider identities without explicit evidence, switch accounts, kill tasks, or block launches. Existing runtime launch records are the future process/account binding hook.

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

The repository test suite covers schema rejection, atomic last-good preservation, independent source updates, two-account identity, stale/unknown states, weekly exhaustion, request replay/content mismatch, concurrent reservations, reconciliation, rotating-card geometry and evidence binding, direct selection, concurrent selection/ingestion/advice updates, compact and tiny rendering, and live PTY rotation, controls, resize, and restart. It also covers distinct rate samples and reserve projections from the current source measurement. CI runs lint, tests, and wheel builds on Python 3.11–3.13.

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
