"""LLM layer: providers, model routing, configuration.

Three-layer config (see docs/architecture/llm-layer.md):

- ``llm_providers.yaml`` — physical provider connections
  (openai_compatible, claude_code_cli, mock).
- ``llm_models.yaml`` — model profiles, each referencing a provider.
- ``config/agents/<role>.yaml`` — per-agent ``llm_config`` block
  (default_model, fallback_chain, temperature, required_capabilities).

Per handoff.md §3.1, the LLM layer transports content generation only.
Routing/gating/scoring decisions live in code (router.py, config_loader.py),
return ``decision_trace`` structures, and never call out to an LLM
themselves.
"""
