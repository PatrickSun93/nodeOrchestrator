"""Demo plugin tool implementations (demo_posture_b, operator-placed).

This plugin is in the operator-placed plugins_dir and runs under Posture A
(in-process importlib, ADR-029 D4).  The host orchestrator DOES import this
module directly.

Fetched plugins (provenance="fetched") would instead run in the subprocess
harness (_harness.py), never in-process.  The env_probe_tool demonstrates the
posture difference: Posture A sees os.environ; Posture B gets a scoped env.
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
