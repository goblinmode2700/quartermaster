## Context

The existing source adapters store a small projection of each input document.
The CLI has no model process. Its `advise` command compares provider percentages.
The current display and state lock remain useful and stay in place.

## Goals / Non-Goals

Goals:

- Preserve source information independently of current display requirements.
- Run the consumer's Claude Code executable with native argument semantics.
- Give both modes the same evidence and advisory instructions.
- Retain inspectable input and headless output without another service.

Non-goals:

- A replacement Claude terminal, agent runtime, or conversation store.
- Automatic quota collection, roster discovery, or scheduled model calls.
- A guarantee that model prose reserves capacity or authorizes a launch.
- A rewrite of the existing assignment request workflow.

## Decisions

### Preserve documents and derive views

Each source snapshot gains `raw`, which contains the complete accepted JSON value.
The existing `accounts` projection remains available for the display.
`status --json` gains `sources`, including raw documents and source provenance.
Unknown fields, last-good history, forecasts, and nested extensions remain intact.
Preservation is semantic JSON preservation, not preservation of whitespace or object key order.
Each new observation replaces only its own source snapshot. This change does not add an unlimited observation history.
Old state has no invented `raw` value. Consultation input identifies sources that need another collection to restore full evidence.

### Adopt the native CLI

Pattern: external command delegation with argument forwarding.
Verdict: adopt Claude Code and Python standard process facilities.

- [Claude CLI](https://code.claude.com/docs/en/cli-reference): interactive sessions, print mode, and file-based prompt additions.
- [uv tools](https://docs.astral.sh/uv/guides/tools/): separate wrapper arguments from child arguments.
- [Python subprocess](https://docs.python.org/3/library/subprocess.html): argument arrays, captured output, timeouts, and exit status.
- Local code: `src/quartermaster/core.py` supplies the existing snapshot lock and atomic state writes.

No external local launcher is copied. Native behavior is the authority for this general-purpose integration.
The consumer supplies Claude Code and its authentication. Each consultation consumes that consumer's normal model allowance.

### Configuration and argument ownership

The optional configuration file is `claude.json` in the state directory. `--config` selects another file.
It contains `executable` and `args`. Arguments are a JSON array of strings, never a shell expression.
An explicit `--` replaces the entire configured argument array, including an empty replacement.
`--claude` overrides the executable. Relative executable paths use the caller's working directory.
Claude flags pass through without a version-specific whitelist.
Standalone `-p` and `--print` select headless execution. `--headless` supplies `-p` as a convenience.

Quartermaster owns one `--append-system-prompt-file` argument for the evidence and advisory instructions.
Consumer append-prompt flags conflict with this argument and produce an explicit error.
Other system-prompt flags, model selection, permission settings, output formats, and session options remain native Claude arguments.
The consultation question uses `--question`. Positional Claude prompts are not part of this forwarding interface.

### Evidence delivery

Each consultation creates a private directory under the selected state directory.
The directory contains `context.json`, `instructions.txt`, and `invocation.json`.
The instructions include the complete JSON packet, so Claude does not need a file-reading tool to access the initial evidence.
The packet contains normalized observations, complete source documents, outstanding assignment requests, and optional consumer context.
The consumer context is a JSON object. It can contain a roster, preferences, proposed work, and additional evidence without a field whitelist.
Source contents remain data, not instructions. The prompt makes that distinction explicit.
An oversized model context produces an upstream failure. Quartermaster does not silently truncate the packet.

### Mode and output behavior

Interactive mode requires terminal input and output and replaces the wrapper with Claude through `exec`.
Claude owns terminal input, signals, history, and session continuation. Quartermaster does not scrape its terminal.
Headless mode captures stdout and stderr as bytes and preserves both files before forwarding them.
It does not force JSON output or parse model prose into a green assignment decision.
The default headless timeout is 120 seconds. `--timeout` changes it.
A timeout terminates only the process group started for that consultation and reports failure, with partial output retained.
`--dry-run` prepares the packet and shows the effective invocation without running Claude.

The shared state lock protects snapshot acquisition, not a whole conversation.
Consultations do not create, cancel, complete, or release assignment requests.
All consultation output refers to its dated snapshot. Later interactive replies do not imply refreshed quota.
Concurrent consultation prose has no reservation guarantee. Consumers must not treat it as admission control.
Connecting interactive decisions to fresh, serialized assignment records needs a separate explicit contract.

## Risks / Trade-offs

- Raw documents can contain private account information. State and consultation files remain local and use private file permissions.
- A consumer who runs `consult` sends that packet through their configured Claude provider.
- Advisory instructions are not a security sandbox. Consumer Claude permissions still control tool access.
- Arbitrary Claude arguments can change behavior. Quartermaster preserves errors and never silently changes conflicting arguments.
- Old discarded fields remain unavailable until the source is ingested again.
- Native interactive output stays in Claude's session history. Only headless output has a Quartermaster report file.
- Fake-executable and PTY tests prove wrapper behavior, not a live provider response or recommendation quality.
