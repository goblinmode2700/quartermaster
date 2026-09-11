# Prior-art decision

Pattern: multi-source quota normalization plus a single-host reservation ledger.

- Adopt `realiti4/claude-swap` v0.26.0 as the Claude credential and collection owner. Its schema-v1 JSON distinguishes current usage, last-good history, and credential states.
- Adopt `kunchenguid/quota-axi` 0.1.41 at `a19268827220e12e173067d11703e6ee36d5d88f` as the non-Claude collector. Its schema-v5 JSON carries provider freshness, windows, and explicit unknown semantics.
- Port the conventional write-lock/read/decide/atomic-replace transaction used by durable local ledgers. Python `fcntl.flock`, `os.replace`, and `fsync` are sufficient for this one-host coordinator.
- Reject a credential engine, daemon, scheduler, database, web UI, automatic switcher, or admission gate. They exceed the advisory boundary and duplicate mature owners.

No upstream source code is copied. Both surveyed upstream projects are MIT licensed.

## Rotating terminal cards

Adopt the existing curses input, background-color, and resize facilities, and the existing `wcwidth` dependency for terminal-cell measurement. Port the terminal-clock presentation pattern: a small fixed block-glyph alphabet, a thick bar, and one card per frame. Keep only an in-process rotation cursor and deadline; this is display timing, not a collection scheduler.

Reuse `Store.locked()` and its atomic state replacement for agent selection. Each display command increments a revision and holds an existing account identity or resumes rotation. No additional transport, daemon, or credential access is needed.
