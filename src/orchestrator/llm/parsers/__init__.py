"""Output parsers for providers that return non-API formats.

Currently:

- ``claude_code_output`` — parses the JSON envelope from
  ``claude --output-format json``.

Provider-side parsing is split out so wire-format upgrades land in a
small, well-tested module without churning routing/health logic.
"""
