"""External-ground-truth connectors that produce external_validation events.

Per ADR-022 D1/D4: connectors live outside memory/ and append via
EventStore.append only (never raw-INSERT). They are leaf consumers.

Connectors are the boundary between the orchestrator's event log and
external validation systems (CI pipelines, dataset checks, benchmark
runners, etc.). They write EXTERNAL_VALIDATION events via emit_external_validation
— the sole construction site for ExternalValidationMeta (ADR-022 D4).
"""
