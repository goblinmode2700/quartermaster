## Purpose

Provide native interactive and headless Claude consultations with complete evidence and consumer-controlled Claude arguments.

## ADDED Requirements

### Requirement: Native modes

The system SHALL run the configured Claude executable in interactive mode or headless print mode.

#### Scenario: Interactive consultation

- **WHEN** a terminal caller requests a consultation without print mode
- **THEN** Claude inherits the terminal and working directory
- **AND** Quartermaster does not implement or scrape a replacement interactive interface

#### Scenario: Headless consultation

- **WHEN** a caller supplies `--headless`, standalone `-p`, or standalone `--print`
- **THEN** Claude runs without interactive terminal input
- **AND** its stdout, stderr, and exit status remain available

#### Scenario: Missing terminal

- **WHEN** interactive mode has no terminal input or output
- **THEN** the command fails with instructions to use print mode
- **AND** it does not silently change modes

### Requirement: Consumer arguments

The system SHALL accept an executable and an argument array from optional JSON configuration.
It SHALL forward child arguments without shell interpolation or a Claude-version whitelist.

#### Scenario: Explicit replacement

- **WHEN** the caller supplies `--` after Quartermaster options
- **THEN** the following arguments replace all configured Claude arguments
- **AND** an empty replacement clears the configured arguments

#### Scenario: Native options

- **WHEN** the caller supplies model, session, permission, or previously unknown Claude flags
- **THEN** those argument strings reach the child unchanged and in order

#### Scenario: Prompt conflict

- **WHEN** consumer arguments contain an append-prompt flag owned by Quartermaster
- **THEN** the command reports the conflicting flag before running Claude
- **AND** it does not silently remove or override the argument

### Requirement: Shared evidence packet

The system SHALL supply the same input structure and advisory instructions to both modes.

#### Scenario: Consumer context

- **WHEN** the caller supplies a JSON context object with roster, preferences, work, or additional fields
- **THEN** the entire object reaches the consultation packet without a field whitelist
- **AND** complete source documents and outstanding assignment requests remain available

#### Scenario: No invented observation

- **WHEN** context, source evidence, or account binding is missing
- **THEN** the packet retains that absence
- **AND** the instructions require the adviser to explain uncertainty instead of inventing evidence

### Requirement: Private and inspectable execution

The system SHALL retain consultation inputs and headless output in private files outside the repository by default.

#### Scenario: Dry run

- **WHEN** the caller requests `--dry-run`
- **THEN** the packet and effective invocation are available for inspection
- **AND** no Claude process runs

#### Scenario: Child failure

- **WHEN** Claude exits unsuccessfully or the executable cannot start
- **THEN** the command returns a failure
- **AND** it does not substitute a deterministic recommendation

#### Scenario: Timeout

- **WHEN** a headless consultation exceeds its timeout
- **THEN** its process group stops and partial output remains available
- **AND** the command returns a timeout failure

### Requirement: Snapshot and assignment boundaries

The system SHALL acquire a consistent state snapshot without holding the shared lock for the conversation.
Consultations SHALL NOT mutate assignment requests or claim a capacity reservation from model prose.

#### Scenario: Concurrent ingestion

- **WHEN** another process ingests evidence during a consultation
- **THEN** ingestion can acquire the state lock
- **AND** the consultation retains its original dated input

#### Scenario: Existing assignment state

- **WHEN** a consultation succeeds, fails, times out, or remains interactive
- **THEN** existing pending and active assignment requests remain unchanged
- **AND** no new green assignment record is inferred from the output
