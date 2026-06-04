"""P3.7-remote-1: remote transport config schema tests (ADR-032 D1).

Covers:
  - streamable_http requires url with https:// scheme (ConfigError on missing/http)
  - stdio unchanged valid (command required, url forbidden)
  - unknown transport → ConfigError
  - existing config/mcp_servers.yaml (all stdio) still loads
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestrator.llm.exceptions import ConfigError
from orchestrator.mcp.config import MCPServerConfig, load_mcp_servers_config

_REAL_CONFIG = Path(__file__).resolve().parent.parent.parent / "config" / "mcp_servers.yaml"


# ---------------------------------------------------------------------------
# streamable_http — valid https:// URL
# ---------------------------------------------------------------------------


def test_streamable_http_valid_https_url() -> None:
    """streamable_http with https:// url → valid config."""
    cfg = MCPServerConfig(
        transport="streamable_http",
        url="https://api.example.com/mcp",
        tools={},
    )
    assert cfg.transport == "streamable_http"
    assert cfg.url == "https://api.example.com/mcp"
    assert cfg.command is None


# ---------------------------------------------------------------------------
# streamable_http — validation failures
# ---------------------------------------------------------------------------


def test_streamable_http_missing_url_raises() -> None:
    """streamable_http without url → ValidationError (ConfigError via loader)."""
    with pytest.raises(ValidationError, match="url"):
        MCPServerConfig(transport="streamable_http", tools={})


def test_streamable_http_http_url_rejected() -> None:
    """streamable_http with http:// (plaintext) → ValidationError (TLS mandatory HR#6)."""
    with pytest.raises(ValidationError, match="https://"):
        MCPServerConfig(
            transport="streamable_http",
            url="http://api.example.com/mcp",
            tools={},
        )


def test_streamable_http_no_scheme_rejected() -> None:
    """streamable_http with bare host (no scheme) → ValidationError."""
    with pytest.raises(ValidationError, match="https://"):
        MCPServerConfig(
            transport="streamable_http",
            url="api.example.com/mcp",
            tools={},
        )


def test_streamable_http_via_yaml_missing_url_config_error(tmp_path: Path) -> None:
    """streamable_http without url via YAML load → ConfigError (fail-closed)."""
    cfg_path = tmp_path / "mcp_servers.yaml"
    cfg_path.write_text(
        """
servers:
  remote_bad:
    transport: streamable_http
    tools: {}
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_mcp_servers_config(cfg_path)


def test_streamable_http_via_yaml_http_scheme_config_error(tmp_path: Path) -> None:
    """streamable_http with http:// via YAML load → ConfigError (TLS mandatory)."""
    cfg_path = tmp_path / "mcp_servers.yaml"
    cfg_path.write_text(
        """
servers:
  remote_bad:
    transport: streamable_http
    url: "http://api.example.com/mcp"
    tools: {}
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_mcp_servers_config(cfg_path)


# ---------------------------------------------------------------------------
# stdio — unchanged valid
# ---------------------------------------------------------------------------


def test_stdio_with_command_valid() -> None:
    """stdio with command → valid; url is null (unused for subprocess)."""
    cfg = MCPServerConfig(command="npx", args=["-y", "server"], tools={})
    assert cfg.transport == "stdio"
    assert cfg.command == "npx"
    assert cfg.url is None


def test_stdio_missing_command_raises() -> None:
    """stdio without command → ValidationError (command required)."""
    with pytest.raises(ValidationError, match="command"):
        MCPServerConfig(transport="stdio", tools={})


# ---------------------------------------------------------------------------
# unknown transport → ValidationError
# ---------------------------------------------------------------------------


def test_unknown_transport_rejected() -> None:
    """Unknown transport value → ValidationError."""
    with pytest.raises(ValidationError, match="transport"):
        MCPServerConfig(transport="sse", command="npx", tools={})


# ---------------------------------------------------------------------------
# existing config/mcp_servers.yaml (all stdio) still loads
# ---------------------------------------------------------------------------


def test_existing_mcp_servers_yaml_loads() -> None:
    """The real config/mcp_servers.yaml (all stdio) loads without ConfigError (no regression)."""
    if not _REAL_CONFIG.exists():
        pytest.skip("config/mcp_servers.yaml not present")
    cfg = load_mcp_servers_config(_REAL_CONFIG)
    for server_name, server_cfg in cfg.servers.items():
        assert server_cfg.transport in {"stdio", "streamable_http"}, (
            f"server {server_name!r}: unexpected transport {server_cfg.transport!r}"
        )
        if server_cfg.transport == "stdio":
            assert server_cfg.command is not None, (
                f"server {server_name!r}: stdio server missing command"
            )


# ---------------------------------------------------------------------------
# streamable_http via valid YAML
# ---------------------------------------------------------------------------


def test_streamable_http_via_yaml_valid(tmp_path: Path) -> None:
    """A valid streamable_http entry in YAML loads cleanly."""
    cfg_path = tmp_path / "mcp_servers.yaml"
    cfg_path.write_text(
        """
servers:
  remote_ok:
    transport: streamable_http
    url: "https://api.example.com/mcp"
    api_key_env: MY_API_KEY
    timeouts:
      connect: 10.0
      list_tools: 10.0
      call_tool: 30.0
    tools:
      list_items:
        reversibility: 10
""",
        encoding="utf-8",
    )
    cfg = load_mcp_servers_config(cfg_path)
    assert "remote_ok" in cfg.servers
    srv = cfg.servers["remote_ok"]
    assert srv.transport == "streamable_http"
    assert srv.url == "https://api.example.com/mcp"
    assert srv.api_key_env == "MY_API_KEY"
    assert srv.tools["list_items"].reversibility == 10
