"""§6 Constitution + schema invariant tests for the mcp/ package.

c1: No upstream layer (core/autonomy/agents/llm/rooms/skills) imports mcp/.
c2: mcp/ does not reference decide_tier/emit_gate_decision/gate/
    select_model_and_provider (no routing/judgment; HR#6).
c3: mcp/ does not import from orchestrator.llm.providers.* (no LLM calls).
c4: No new LLMPurpose values beyond the frozen set (HR#5).
c5: All namespaced MCP tool names are collision-free vs local tools
    (mcp__ prefix absent from tools.yaml; ADR-027 D3).
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator"
_MCP_PKG = _SRC / "mcp"


# ---------------------------------------------------------------------------
# c1: No upstream layer imports mcp/
# ---------------------------------------------------------------------------


def test_constitution_c1_no_upstream_import_of_mcp() -> None:
    """Upstream layers must NOT import orchestrator.mcp.* (mcp/ is a leaf consumer)."""
    upstream_roots = [
        _SRC / "core",
        _SRC / "autonomy",
        _SRC / "agents",
        _SRC / "llm",
        _SRC / "rooms",
        _SRC / "skills",
        _SRC / "connectors",
        _SRC / "memory",
        _SRC / "producers",
        _SRC / "reentry",
        _SRC / "derived",
        _SRC / "workflow",
    ]
    violations: list[str] = []
    for root in upstream_roots:
        if not root.exists():
            continue
        for py_path in root.rglob("*.py"):
            if "__pycache__" in py_path.parts:
                continue
            source = py_path.read_text(encoding="utf-8")
            if "orchestrator.mcp" in source or "from orchestrator.mcp" in source:
                tree = ast.parse(source, filename=str(py_path))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        module = ""
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                module = alias.name
                        elif node.module:
                            module = node.module
                        if module.startswith("orchestrator.mcp"):
                            violations.append(f"  {py_path}: line {node.lineno}: {module}")
    assert not violations, "c1 guard: upstream layer imports orchestrator.mcp.*:\n" + "\n".join(
        violations
    )


# ---------------------------------------------------------------------------
# c2: mcp/ does not reference routing/decision symbols (HR#6)
# ---------------------------------------------------------------------------


_FORBIDDEN_IN_MCP = frozenset(
    {
        "decide_tier",
        "emit_gate_decision",
        "select_model_and_provider",
    }
)
_GATE_FORBIDDEN = "gate"  # checked separately (common word, use AST)


def test_constitution_c2_no_routing_in_mcp() -> None:
    """mcp/ must not call decide_tier/emit_gate_decision/gate/select_model_and_provider."""
    violations: list[str] = []
    for py_path in _MCP_PKG.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        source = py_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Name, ast.Attribute)):
                continue
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in _FORBIDDEN_IN_MCP:
                violations.append(f"  {py_path}: line {node.lineno}: {name!r} referenced")
            # "gate" as a standalone Name (not attribute) — detect imports
            if name == _GATE_FORBIDDEN and isinstance(node, ast.Name):
                violations.append(f"  {py_path}: line {node.lineno}: {name!r} referenced as Name")
    assert not violations, "c2 guard: mcp/ references routing/decision symbols:\n" + "\n".join(
        violations
    )


# ---------------------------------------------------------------------------
# c3: mcp/ does not import from orchestrator.llm.providers.*
# ---------------------------------------------------------------------------


def test_constitution_c3_no_llm_provider_import_in_mcp() -> None:
    """mcp/ must not import from orchestrator.llm.providers.* (no LLM calls)."""
    violations: list[str] = []
    for py_path in _MCP_PKG.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        source = py_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("orchestrator.llm.providers")
            ):
                violations.append(f"  {py_path}: line {node.lineno}: {node.module}")
    assert not violations, (
        "c3 guard: mcp/ imports from orchestrator.llm.providers.*:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# c4: No new LLMPurpose values (HR#5 — no new routing purpose)
# ---------------------------------------------------------------------------


_KNOWN_PURPOSES = frozenset(
    {
        "AGENT_RESPONSE",
        "SNAPSHOT_SEMANTIC",
        "HYPOTHESIS_CANDIDATE",
        "KEY_NODE_CANDIDATE",
        "TOOL_OUTPUT_INTERPRET",
        "TERM_DEFINITION_PROPOSAL",
        "REENTRY_DIGEST_RENDER",
        "ARCHIVE_SUMMARY_RENDER",
        "HYPOTHESIS_TAG_PROPOSAL",
    }
)


def test_constitution_c4_no_new_llm_purpose() -> None:
    """LLMPurpose enum must not gain new values beyond the frozen set (HR#5)."""
    from orchestrator.llm.purposes import LLMPurpose

    actual = frozenset(p.name for p in LLMPurpose)
    new_values = actual - _KNOWN_PURPOSES
    assert not new_values, (
        f"c4 guard: new LLMPurpose values detected (require ADR + HR#5 update): "
        f"{sorted(new_values)}"
    )


# ---------------------------------------------------------------------------
# c5: Namespacing collision-free — mcp__ prefix absent from tools.yaml
# ---------------------------------------------------------------------------


def test_constitution_c6_no_verify_false_in_remote_transport() -> None:
    """TLS guard (R0-B Y4, ADR-032 D5): verify=False must not appear in mcp/ files.

    The remote transport uses host-built httpx.AsyncClient(verify=True) explicitly.
    A verify=False anywhere in mcp/ would disable TLS certificate verification,
    allowing MITM attacks on remote MCP endpoints.

    Scans: mcp/transport.py + all other mcp/ .py files for the literal patterns
      verify=False  or  verify = False  or  "verify": False
    Zero occurrences required (discriminating test — the scan MUST find mcp/ files).
    """
    import re

    # Two patterns: bare keyword argument and string-dict key
    patterns = [
        re.compile(r"verify\s*=\s*False"),
        re.compile(r'"verify"\s*:\s*False'),
        re.compile(r"'verify'\s*:\s*False"),
    ]

    violations: list[str] = []
    scanned = 0
    for py_path in _MCP_PKG.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        source = py_path.read_text(encoding="utf-8")
        scanned += 1
        for line_no, line in enumerate(source.splitlines(), 1):
            for pat in patterns:
                if pat.search(line):
                    violations.append(f"  {py_path}:{line_no}: {line.strip()!r}")

    assert scanned > 0, "c6 non-vacuous: no mcp/ .py files found to scan"
    assert not violations, (
        "c6 TLS guard: verify=False found in mcp/ — TLS must ALWAYS be enabled:\n"
        + "\n".join(violations)
    )


def test_constitution_c5_no_namespace_collision() -> None:
    """Local tool names in tools.yaml must not start with 'mcp__'."""
    from orchestrator.llm.config_loader import load_tools_config

    tools_yaml = Path(__file__).resolve().parent.parent.parent / "config" / "tools.yaml"
    if not tools_yaml.exists():
        return
    tools = load_tools_config(tools_yaml)
    collisions = [name for name in tools if name.startswith("mcp__")]
    assert not collisions, (
        f"c5 guard: local tool names start with 'mcp__' (collision risk): {collisions}"
    )


# ---------------------------------------------------------------------------
# §6 Schema invariants: MCPServersConfig + adapter mapping frozen/validated
# ---------------------------------------------------------------------------


def test_schema_mcp_server_config_frozen() -> None:
    """MCPServerConfig must be frozen (immutable after construction)."""
    import pytest

    from orchestrator.mcp.config import MCPServerConfig

    cfg = MCPServerConfig(command="npx", args=["-y", "test"])
    with pytest.raises((TypeError, ValueError)):
        cfg.command = "evil"  # Pydantic frozen=True raises ValidationError at runtime


def test_schema_mcp_server_config_extra_forbid() -> None:
    """MCPServerConfig must reject unknown fields."""
    import pytest
    from pydantic import ValidationError

    from orchestrator.mcp.config import MCPServerConfig

    with pytest.raises(ValidationError):
        MCPServerConfig(command="npx", unknown_field="bad")  # type: ignore[call-arg]


def test_schema_mcp_tool_config_defaults() -> None:
    """MCPToolConfig reversibility defaults to 0 (conservative-low per ADR-005 D2)."""
    from orchestrator.mcp.config import MCPToolConfig

    cfg = MCPToolConfig()
    assert cfg.reversibility == 0


def test_schema_mcp_tool_config_range() -> None:
    """MCPToolConfig reversibility must be 0-10."""
    import pytest
    from pydantic import ValidationError

    from orchestrator.mcp.config import MCPToolConfig

    with pytest.raises(ValidationError):
        MCPToolConfig(reversibility=11)
    with pytest.raises(ValidationError):
        MCPToolConfig(reversibility=-1)

    # Boundary values should work
    assert MCPToolConfig(reversibility=0).reversibility == 0
    assert MCPToolConfig(reversibility=10).reversibility == 10


def test_schema_mcp_servers_config_extra_forbid() -> None:
    """MCPServersConfig must reject unknown top-level fields."""
    import pytest
    from pydantic import ValidationError

    from orchestrator.mcp.config import MCPServersConfig

    with pytest.raises(ValidationError):
        MCPServersConfig(servers={}, rogue_field="bad")  # type: ignore[call-arg]


def test_schema_load_mcp_servers_config_missing_file() -> None:
    """load_mcp_servers_config raises ConfigError for missing file."""
    import pytest

    from orchestrator.llm.exceptions import ConfigError
    from orchestrator.mcp.config import load_mcp_servers_config

    with pytest.raises(ConfigError, match="does not exist"):
        load_mcp_servers_config(Path("/nonexistent/mcp_servers.yaml"))


def test_schema_load_mcp_servers_config_valid(tmp_path: Path) -> None:
    """load_mcp_servers_config parses a valid config."""
    from orchestrator.mcp.config import load_mcp_servers_config

    cfg_path = tmp_path / "mcp_servers.yaml"
    cfg_path.write_text(
        """
servers:
  filesystem:
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    api_key_env: null
    env: {}
    tools:
      read_file:
        reversibility: 10
      write_file:
        reversibility: 2
""",
        encoding="utf-8",
    )
    cfg = load_mcp_servers_config(cfg_path)
    assert "filesystem" in cfg.servers
    fs = cfg.servers["filesystem"]
    assert fs.command == "npx"
    assert fs.tools["read_file"].reversibility == 10
    assert fs.tools["write_file"].reversibility == 2


def test_schema_load_mcp_servers_config_schema_violation(tmp_path: Path) -> None:
    """load_mcp_servers_config raises ConfigError on schema violation."""
    import pytest

    from orchestrator.llm.exceptions import ConfigError
    from orchestrator.mcp.config import load_mcp_servers_config

    cfg_path = tmp_path / "mcp_servers.yaml"
    cfg_path.write_text(
        """
servers:
  bad_server:
    command: npx
    unknown_field: oops
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_mcp_servers_config(cfg_path)
