## Purpose

Preserve complete accepted quota documents so future consumers can inspect evidence beyond the display's current fields.

## ADDED Requirements

### Requirement: Complete source documents

The system SHALL retain each accepted source document as `raw` beside its normalized projection.

#### Scenario: Unknown source extensions

- **WHEN** a supported document contains additional nested fields, arrays, nulls, forecasts, or last-good history
- **THEN** its stored `raw` value equals the input JSON value
- **AND** ingestion does not remove those fields

### Requirement: Full JSON access

The system SHALL expose source snapshots, including `raw`, through `status --json` and consultation input.

#### Scenario: Display projection is smaller than source evidence

- **WHEN** the display uses only a subset of a source document
- **THEN** JSON consumers still receive the complete document under `sources`

### Requirement: Compatible and isolated updates

The system SHALL retain existing source, request, and display state during unrelated updates.

#### Scenario: Legacy state

- **WHEN** a stored source has no `raw` value
- **THEN** status and display remain readable
- **AND** consultation input identifies incomplete source preservation without inventing missing fields

#### Scenario: Invalid input

- **WHEN** ingestion rejects a malformed document
- **THEN** the existing raw and normalized snapshot remain unchanged

#### Scenario: Independent source replacement

- **WHEN** one source receives a new accepted document
- **THEN** only that source's snapshot is replaced
- **AND** other sources, requests, and display selection remain unchanged
