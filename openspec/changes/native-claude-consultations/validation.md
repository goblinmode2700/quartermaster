# Validation results

Date: 2026-09-11.
Package: `quartermaster-quota 0.3.0.dev0`. This is an unpublished development version.

## Passed checks

- Strict OpenSpec validation for `native-claude-consultations`.
- Ruff checks and `git diff --check`.
- Focused consultation suite: 33 tests, including source preservation and process behavior.
- Source distribution and wheel build.
- Full suite against the installed wheel: 133 tests passed on macOS with Python 3.13.12.
- Installed command help and dry-run packet preparation outside the source checkout.

The installed-package check used a disposable environment, not an editable installation.
The imported package path was inside that environment's `site-packages` directory.

## Behavioral evidence

The fake executable receives exact arguments, full context, and preserved source documents.
It runs through the real CLI process boundary without a provider connection.
Tests cover native terminal inheritance, interactive process replacement, and concurrent state access.
They also cover nonzero exit, missing executable, private file permissions, timeout, termination, and retained partial output.
Existing display and assignment tests remain in the full suite.

## Remaining limits

No live Claude request or quota collection ran during these checks.
The tests do not establish provider authentication, model recommendation quality, or compatibility with every installed Claude version.
Consumer roster collection, scheduled observation, and automatic report delivery remain external integrations.
Consultation output does not create an assignment reservation. Interactive output remains in Claude's native session history.

The selected integration follows Claude's documented prompt-file and native mode contracts.
A consumer must check their installed Claude invocation before relying on unattended consultations.
