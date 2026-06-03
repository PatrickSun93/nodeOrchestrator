"""PluginManifest Pydantic schema (ADR-029 D1).

A plugin manifest is a frozen, schema-versioned Pydantic model that declares
all contributions a plugin bundle ships: roles, skills, tool-classifications,
executable tool code references, and MCP-server configs.  Unknown fields in
the YAML raise ValidationError (extra="forbid"), fail-closing the loader.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Host plugin-contract version (bump when the loader API changes in a
# breaking way; P3.7 migration path — ADR-029 D6 / plan §5 clean note).
PLUGIN_HOST_CONTRACT_VERSION: int = 1

# Loader rejects manifests with an unknown schema_version (HR#5 / D1).
SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})


class PluginContributions(BaseModel):
    """Declared contribution surfaces (all optional; a plugin ships only what it has)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    roles: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    # Executable tool code: name → "<module>:<callable>" within the plugin dir.
    # Admit-code surface — see ADR-029 D4 + inscribed L1/L1b/L2 exposures.
    tool_impls: dict[str, str] = Field(default_factory=dict)
    mcp_servers: list[str] = Field(default_factory=list)

    @field_validator("tool_impls")
    @classmethod
    def _validate_impl_refs(cls, v: dict[str, str]) -> dict[str, str]:
        for name, ref in v.items():
            parts = ref.split(":")
            if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                raise ValueError(f"tool_impl {name!r}: ref {ref!r} must be '<module>:<callable>'")
        return v


class PluginDependencies(BaseModel):
    """Runtime dependencies the host must satisfy (fail-closed if unmet, HR#5 / D6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Each model_id must exist in the host ModelRegistry.
    model_ids: list[str] = Field(default_factory=list)
    # Each room_type must exist in the host's supported room types.
    room_types: list[str] = Field(default_factory=list)
    # Host plugin-contract version must be >= this value.
    min_host_contract: int = Field(default=1, ge=1)


class PluginManifest(BaseModel):
    """Frozen, extra="forbid", schema-versioned plugin manifest (ADR-029 D1).

    An unknown schema_version → ValidationError → fail-closed refuse (HR#5).
    All contribution/dependency fields are optional with safe empty defaults.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    contributions: PluginContributions = Field(default_factory=PluginContributions)
    dependencies: PluginDependencies = Field(default_factory=PluginDependencies)

    @field_validator("schema_version")
    @classmethod
    def _check_schema_version(cls, v: int) -> int:
        if v not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"unsupported schema_version {v!r}; supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        return v
