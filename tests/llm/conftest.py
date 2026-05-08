"""Shared fixtures for tests/llm/.

Implementations land in P1.1 commit 2 alongside the impl. This file
declares the fixture shapes so reviewers can see the intended test
surface during interface freeze.

Planned fixtures (commit 2):

- ``mock_provider`` — a fresh ``MockProvider`` with no canned
  responses; tests register via ``mock_provider.responses[...] = [...]``.
- ``example_provider_registry`` — ``ProviderRegistry`` containing
  one mock provider only (no real network).
- ``example_model_registry`` — ``ModelRegistry`` with the 6 models
  from ``llm_models.yaml.example``, all routed at the mock provider
  (so tests can exercise routing logic without live providers).
- ``example_agent_configs`` — dict of role-name → ``AgentLLMConfig``
  parsed from the example agent YAML files.
- ``recorded_llm_call(name)`` — VCR-style fixture that replays a
  pre-recorded provider response for higher-fidelity tests
  (recordings live in ``tests/llm/recordings/``; format documented
  in that directory's README).

The ``orchestrator.core`` ``in_memory_event_store`` fixture
(``tests/core/conftest.py``) is reused via pytest's automatic
conftest discovery — LLM tests that need an event log to record
calls into share that fixture rather than re-rolling their own.
"""

from __future__ import annotations
