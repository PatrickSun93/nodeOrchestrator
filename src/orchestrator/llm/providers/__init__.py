"""Provider implementations satisfying ``LLMProvider`` Protocol.

P1 set:

- ``openai_compatible`` — DeepSeek, Ollama, MLX, anything OpenAI Chat
  Completions-shaped.
- ``claude_code_cli`` — Anthropic models routed via the ``claude`` CLI
  subprocess (Max subscription quota).
- ``agy_cli`` — Gemini models routed via the ``agy`` CLI subprocess.
- ``mock`` — test-only deterministic provider.

A new provider type means a new module here plus a registry entry in
``config_loader``. The Protocol surface is in ``orchestrator.llm.protocol``.
"""
