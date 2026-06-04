"""MCPServersConfig: per-server config + pre-classify tool allowlist.

Frozen Pydantic models with extra="forbid" (ADR-027 D3/D5, ADR-032 D1).
Loader mirrors load_tools_config pattern (ConfigError on bad yaml/schema).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from orchestrator.llm.exceptions import ConfigError


class MCPToolConfig(BaseModel):
    """Per-tool pre-classify config entry (ADR-027 D3).

    reversibility is the CODE-classified value (0-10). Server hints ignored.
    Default 0 = irreversible → HARD_CONFIRM (conservative-low per ADR-005 D2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    reversibility: int = Field(default=0, ge=0, le=10)


class MCPTimeouts(BaseModel):
    """Per-server bounded timeout values in seconds (ADR-027 D1).

    Defaults: connect/list_tools 10 s, call_tool 30 s.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    connect: float = Field(default=10.0, gt=0)
    list_tools: float = Field(default=10.0, gt=0)
    call_tool: float = Field(default=30.0, gt=0)


class MCPServerConfig(BaseModel):
    """One server entry from mcp_servers.yaml (ADR-027 D3/D4, ADR-032 D1).

    transport: "stdio" (subprocess) or "streamable_http" (remote, ADR-032 D1).
    For stdio: command is required (subprocess launch).
    For streamable_http: url is required and must use https:// (TLS mandatory, HR#6).
    api_key_env: credential indirection for both transports — never inline (HR#5).
    env: minimal scoped subprocess env additions for stdio (HR#10); unused for remote.
    tools: pre-classify allowlist — only these tools are callable (HR#2/#3).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    transport: str = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    api_key_env: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    timeouts: MCPTimeouts = Field(default_factory=MCPTimeouts)
    tools: dict[str, MCPToolConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_transport_fields(self) -> MCPServerConfig:
        if self.transport == "stdio":
            if self.command is None:
                raise ValueError("stdio transport requires 'command'")
        elif self.transport == "streamable_http":
            if self.url is None:
                raise ValueError("streamable_http transport requires 'url'")
            if not self.url.startswith("https://"):
                raise ValueError(f"streamable_http url must use https:// scheme, got: {self.url!r}")
        else:
            raise ValueError(
                f"transport must be 'stdio' or 'streamable_http', got: {self.transport!r}"
            )
        return self


class MCPServersConfig(BaseModel):
    """Root config model for mcp_servers.yaml."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


def load_mcp_servers_config(path: Path) -> MCPServersConfig:
    """Load config/mcp_servers.yaml (mirrors load_tools_config pattern).

    Raises:
        ConfigError: missing file, malformed yaml, or schema violation.
    """
    if not path.exists():
        raise ConfigError(f"mcp_servers.yaml does not exist: {path}")

    raw_text = path.read_text(encoding="utf-8")
    raw: Any = yaml.safe_load(raw_text)

    if not isinstance(raw, dict):
        raise ConfigError(f"{path.stem}: expected a mapping at root, got {type(raw).__name__}")

    try:
        return MCPServersConfig(**raw)
    except ValidationError as exc:
        violations = [
            f"{path.stem}: {'.'.join(str(loc) for loc in err['loc'])} — {err['msg']}"
            for err in exc.errors()
        ]
        raise ConfigError("mcp_servers.yaml schema violations:\n" + "\n".join(violations)) from exc
