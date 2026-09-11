## Why

The current tool discards source fields and substitutes a percentage-based rule for a Claude consultation.
Consumers need the actual Claude adviser, in interactive and headless modes, with their own Claude arguments.

## What Changes

- Preserve each accepted source document alongside its derived display fields.
- Expose complete source documents through JSON output.
- Add `consult` with native interactive Claude and headless `claude -p` execution.
- Accept an executable path, saved argument defaults, and an explicit argument replacement after `--`.
- Supply quota evidence, existing request records, and an optional consumer context document to both modes.
- Preserve headless stdout, stderr, exit status, and the exact consultation input outside the repository.
- Keep interactive terminal behavior and conversation history with Claude Code.
- Describe legacy `advise` as a separate, limited heuristic. Do not present its output as a Claude recommendation.

## Capabilities

### New Capabilities

- `source-evidence`: Preserve accepted source documents without a field whitelist.
- `claude-consultation`: Consult Claude Code in either native mode with consumer arguments and retained evidence.

### Modified Capabilities

None. This repository has no existing OpenSpec capabilities.

## Impact

This change affects ingestion, JSON output, the CLI, documentation, and tests.
It adds no Python runtime dependency. Consultations require an installed, authenticated Claude Code executable.
Existing state remains readable. Evidence discarded by older versions cannot be reconstructed.
No collector, credential switch, scheduler, deployment, or publication runs as part of this change.
