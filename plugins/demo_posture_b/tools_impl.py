"""Demo Posture-B plugin tool implementations.

These run inside the subprocess harness — the host orchestrator never imports
this module.  The isolation boundary is the subprocess.
"""

from __future__ import annotations

import os

from orchestrator.tools.executor import LocalToolOutput


def echo_tool(params: dict) -> LocalToolOutput:
    """Echo the 'message' param or return a fixed string."""
    msg = params.get("message", "posture-b-echo-default")
    return LocalToolOutput(content=str(msg))


def env_probe_tool(params: dict) -> LocalToolOutput:
    """Probe whether a specific env key is visible to the subprocess.

    Used in env-leak tests: the key should be absent (scoped env).
    """
    key = str(params.get("key", ""))
    val = os.environ.get(key, "__absent__")
    return LocalToolOutput(content=val)
