"""Executable plugin tool-code loader — Posture A in-process import (ADR-029 D4).

Posture A (ARCHITECT-ACCEPTED): importlib loads the plugin module in-process,
like the host's own build_local_tool_registry() builtins.  Called ONLY after
loader.py's collision-check cleared (ADR-029 D2 step 5; R0-B R1).

Fully-inscribed exposures accepted by architect (2026-06-03):
  L1  — No technical isolation + zero credential/env protection.
         In-process plugin code runs with full host privilege (FS, network,
         os.environ — every API key/secret).  ADR-027 D4 credential-indirection
         + scoped-env are MCP-subprocess-only; they provide ZERO protection here.
  L1b — Import-time code is ungated by construction.  importlib exec_module()
         runs the module top-level at boot before any gate/room/turn exists.
         Curation is the only control; step-ordering ensures this runs only
         after the validate+collision gauntlet, never before a refusal.
  L2  — Posture A VOIDS ADR-028 D5's absolute per-turn liveness bound for the
         plugin-local path — server-wide DoS blast radius.  One buggy curated
         tool blocks the max_workers=1 writer for every room, indefinitely,
         with no cap and no kill (in-process is unkillable).

Fail-closed-against-breakage IS fully delivered (HR#5): a bad import / bad
manifest / collision / unmet dependency → plugin refused at load; a raise at
call → TOOL_FAILED for that call (per-call isolation, ADR-028 D4 via executor).

Posture B (subprocess isolation) is reserved for P3.7 (untrusted remote
provenance) — see ADR-029 D4 Reversibility and the A→B migration surface.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

from orchestrator.tools.executor import LocalToolFn


class PluginCodeLoadError(Exception):
    """Raised when a plugin's executable tool code cannot be loaded."""


def _import_module_from_file(file_path: Path, unique_module_name: str) -> types.ModuleType:
    """Load a Python module from an absolute file path without touching sys.path.

    Uses spec_from_file_location to import without registering in sys.modules,
    keeping the host namespace clean and avoiding cross-plugin module-name
    collisions.  Top-level code in the module runs here (L1b — inscribed).
    """
    spec = importlib.util.spec_from_file_location(unique_module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot create module spec from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_plugin_code(
    plugin_dir: Path,
    plugin_id: str,
    tool_impls: dict[str, str],
) -> dict[str, LocalToolFn]:
    """Load executable tool implementations from a plugin directory (Posture A, D4).

    Each entry in tool_impls maps a tool name to "<module>:<callable>" where
    <module> is a .py file relative to plugin_dir (no extension).

    Import runs ONLY after loader.py cleared validation + collision-check
    (ADR-029 D2 step 5; R0-B R1).  Per-plugin isolation: any import error
    or missing callable → raises PluginCodeLoadError (caller refuses plugin).
    Per-call fail-closed is inherited from the executor (_execute_local_call
    try/except → TOOL_FAILED, ADR-028 D4) — no extra wrapping needed here.
    """
    result: dict[str, LocalToolFn] = {}

    for tool_name, ref in tool_impls.items():
        module_name, callable_name = ref.split(":", 1)
        module_file = plugin_dir / f"{module_name}.py"

        if not module_file.exists():
            raise PluginCodeLoadError(
                f"plugin {plugin_id!r}: module file {module_file} does not exist"
            )

        unique_name = f"orchestrator_plugin_{plugin_id}_{module_name}"
        try:
            module = _import_module_from_file(module_file, unique_name)
        except Exception as exc:
            raise PluginCodeLoadError(
                f"plugin {plugin_id!r}: cannot import module {module_name!r}: {exc}"
            ) from exc

        impl = getattr(module, callable_name, None)
        if impl is None:
            raise PluginCodeLoadError(
                f"plugin {plugin_id!r}: module {module_name!r} has no attribute {callable_name!r}"
            )
        if not callable(impl):
            raise PluginCodeLoadError(
                f"plugin {plugin_id!r}: {module_name}.{callable_name} is not callable"
            )

        result[tool_name] = impl

    return result
