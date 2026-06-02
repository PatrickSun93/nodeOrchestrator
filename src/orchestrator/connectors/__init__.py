"""External-ground-truth connectors that produce external_validation events.

Per ADR-022 D1/D4: connectors live outside memory/ and append via
EventStore.append only (never raw-INSERT). They are leaf consumers.
"""
