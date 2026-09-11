# Prior-art decision

Pattern: multi-source quota views plus single-host assignment coordination.

- Adopt `realiti4/claude-swap` v0.26.0 as the Claude credential and collection owner. Its schema-v1 JSON distinguishes current usage, last-good history, and credential states.
- Adopt `kunchenguid/quota-axi` 0.1.41 at `a19268827220e12e173067d11703e6ee36d5d88f` as the non-Claude collector. Its schema-v5 JSON carries provider freshness, windows, and explicit unknown semantics.
- Port the conventional write-lock/read/decide/atomic-replace transaction for local state. Python `fcntl.flock`, `os.replace`, and `fsync` are sufficient for this one-host coordinator.
- Reject a credential engine, daemon, scheduler, database, web UI, automatic switcher, or admission gate. They exceed the advisory boundary and duplicate mature owners.

No upstream source code is copied. Both surveyed upstream projects are MIT licensed.

## Rotating terminal cards

Adopt the existing curses input, background-color, and resize facilities, and the existing `wcwidth` dependency for terminal-cell measurement. Port the terminal-clock presentation pattern: a small fixed block-glyph alphabet, a thick bar, and one card per frame. Keep only an in-process rotation cursor and deadline; this is display timing, not a collection scheduler.

Reuse `Store.locked()` and its atomic state replacement for agent selection. Each `view` command increments a revision and holds an existing account identity or resumes rotation. No additional transport, daemon, or credential access is needed.

## Quota evidence consistency

The display follows quota-axi's existing effective-availability calculation: the minimum percentage among each scope's referenced windows. It checks reported values against those windows and rejects contradictions. See [the upstream implementation](https://github.com/kunchenguid/quota-axi/blob/main/src/interpretation.ts).

## Native Claude consultations

Pattern: external command delegation with argument forwarding.
Verdict: adopt Claude Code and the Python standard library.

- [Claude CLI reference](https://code.claude.com/docs/en/cli-reference): native interactive mode, print mode, session options, and file-based prompt additions.
- [uv tools](https://docs.astral.sh/uv/guides/tools/): a wrapper separates its options from the child command's arguments.
- [Python subprocess](https://docs.python.org/3/library/subprocess.html): argument arrays, output files, exit codes, and bounded execution.
- Local reference: `src/quartermaster/core.py` supplies the existing snapshot lock. No external local launcher is copied.

The consumer supplies an installed, authenticated Claude executable and its normal model allowance.
Quartermaster supplies evidence and advisory instructions. It does not duplicate Claude's terminal or manage Claude session history.
Interactive mode uses native process replacement. Headless mode retains child output without a forced response schema.
No new Python dependency, PTY relay, daemon, or orchestration framework is required.

Source preservation is additive: retain the complete document and derive the existing display fields alongside it.
The [OpenSpec design](../openspec/changes/native-claude-consultations/design.md) records argument conflicts, file privacy, and assignment boundaries.
