"""Constitutional tests for the LLM layer.

These tests are guardrails. If a future PR breaks one, the test
fails and forces the contributor to think about whether they're
really violating an architectural invariant — or whether the
invariant itself needs an ADR to change.

Each test name starts with ``test_constitution_`` to flag it as
load-bearing. The first constitutional test in the project is
``test_constitution_append_only_at_schema_level`` in
``tests/core/test_constitution.py``; this file follows the same
pattern for the LLM layer.

The fourth LLM-layer constitutional test —
``test_constitution_round_robin_uses_matched_key`` — lives in
``test_mock_provider.py`` because it is a behavioral lock on a
specific class's docstring contract.
"""

from __future__ import annotations

import dataclasses
import inspect
from inspect import iscoroutinefunction
from pathlib import Path

from orchestrator.llm.config_loader import PROVIDER_TYPE_REGISTRY

# All paths are computed relative to the project root.
SRC_ROOT = Path(__file__).resolve().parent.parent.parent / "src"


def test_constitution_all_registered_types_implement_protocol() -> None:
    """Every entry in ``PROVIDER_TYPE_REGISTRY`` structurally
    implements the ``LLMProvider`` Protocol.

    Why: ``PROVIDER_TYPE_REGISTRY`` is typed as ``dict[ProviderType,
    type[Any]]`` (see config_loader.py TODO comment); the static type
    is intentionally loose. This runtime test is the project's
    backstop against drift — when a new provider class is added to
    the registry but only partially implements the Protocol surface,
    config loading might succeed but ``router.py``'s call sites would
    fail at first use. Catch it here instead.

    Locks: ``provider_id`` field, ``can_use_orchestrator_tools``,
    ``health_check`` (sync), ``call`` (must be ``async def``).
    """
    for ptype, cls in PROVIDER_TYPE_REGISTRY.items():
        label = f"PROVIDER_TYPE_REGISTRY[{ptype.value!r}] = {cls.__name__}"

        # provider_id must be a dataclass field (we use @dataclass
        # for all three concrete provider classes).
        assert dataclasses.is_dataclass(cls), f"{label}: not a dataclass"
        field_names = {f.name for f in dataclasses.fields(cls)}
        assert "provider_id" in field_names, (
            f"{label}: missing 'provider_id' dataclass field (fields: {sorted(field_names)})"
        )

        # Methods must exist
        for method in ("can_use_orchestrator_tools", "health_check", "call"):
            attr = getattr(cls, method, None)
            assert callable(attr), f"{label}: missing or non-callable {method!r}"

        # call must be async (the load-bearing async commitment).
        # cls is `type[Any]` per the loose registry typing; mypy can't
        # see `.call` statically, but the hasattr/callable check above
        # guarantees it exists at runtime.
        assert iscoroutinefunction(cls.call), (  # type: ignore[attr-defined]
            f"{label}: call must be 'async def' (see ADR-002 reasoning on async-first)"
        )


def test_constitution_provider_call_signature_consistency() -> None:
    """All registered provider classes' ``.call`` methods have the
    same parameter set. Catches **freeze-vs-impl drift** on the
    Protocol surface — adding/removing a parameter on Protocol but
    not propagating to all implementations, or vice versa.

    The check is a pure structural comparison; if Protocol ever
    legitimately gains a parameter, this test fails until every
    provider's ``call`` is updated to match. That failure is the
    forcing function: silent signature changes don't ship.

    Locks (P1.1 commit 2 + third review): ``self``, ``request``,
    ``model``, ``model_id_requested``. Updating this set requires:
    1. Updating ``LLMProvider`` Protocol in ``protocol.py``,
    2. Updating every concrete provider in ``providers/``,
    3. Updating this expected set,
    4. Disclosing the change in the commit message tracking table.
    """
    expected = {"self", "request", "model", "model_id_requested"}
    for ptype, cls in PROVIDER_TYPE_REGISTRY.items():
        actual = set(inspect.signature(cls.call).parameters.keys())
        assert actual == expected, (
            f"PROVIDER_TYPE_REGISTRY[{ptype.value!r}] = {cls.__name__}: "
            f"call signature drift. expected {sorted(expected)}, got {sorted(actual)}"
        )


def test_constitution_no_provider_class_accepts_kwargs() -> None:
    """Provider classes don't accept ``**kwargs`` on ``__init__`` or
    ``.call``.

    Why: ``**kwargs`` lets yaml mistypes silently slip through.
    A user typo like ``api_key_envv: DEEPSEEK_API_KEY`` would be
    accepted by a kwargs-accepting constructor and only surface as
    "401 Unauthorized" on the first call, with no obvious link back
    to the typo. Per the project's schema-level enforcement
    preference (memory ``feedback_schema_enforcement``), unknown
    fields must fail at construction.

    The closed signature plus ``config_loader``'s try/except around
    instantiation is the project's catch for yaml typos.
    """
    for ptype, cls in PROVIDER_TYPE_REGISTRY.items():
        for method_name in ("__init__", "call"):
            method = getattr(cls, method_name)
            sig = inspect.signature(method)
            for param in sig.parameters.values():
                assert param.kind != inspect.Parameter.VAR_KEYWORD, (
                    f"{cls.__name__}.{method_name} accepts **{param.name} "
                    f"(provider type {ptype.value!r}). Forbidden — yaml "
                    f"typos must fail at construction, not at first call."
                )


def test_constitution_no_hardcoded_model_names() -> None:
    """``src/orchestrator/`` must not contain hardcoded model name
    string literals. Model names belong in
    ``config/llm_models.yaml`` (or its ``.example``); putting them
    in code makes the model-swap ergonomic (one yaml line) impossible.

    The forbidden set covers both API model names (the wire-format
    string a provider uses) and internal ``ModelId`` values (the
    keys in ``llm_models.yaml``). Both leaks defeat the layer split.

    If a legitimate use case appears (e.g., a fallback default
    embedded in code), add an ADR explaining why and an explicit
    allowlist below — don't just delete the entry.
    """
    forbidden_substrings = {
        # API model names
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "qwen2.5-30b-instruct",
        # Internal ModelId values
        "claude_code_opus_47",
        "claude_code_sonnet_46",
        "claude_code_haiku_45",
        "deepseek_v4_pro",
        "deepseek_v4_flash",
        "qwen_mlx_30b",
    }

    violations: list[str] = []
    for py_path in SRC_ROOT.rglob("*.py"):
        # Skip __pycache__
        if "__pycache__" in py_path.parts:
            continue
        try:
            content = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = py_path.relative_to(SRC_ROOT)
        for needle in forbidden_substrings:
            if needle in content:
                violations.append(f"  {rel}: {needle!r}")

    assert not violations, (
        "hardcoded model names in src/orchestrator (move to "
        "config/llm_models.yaml.example):\n" + "\n".join(violations)
    )


def test_constitution_no_llm_calls_in_autonomy_module() -> None:
    """The autonomy module (``src/orchestrator/autonomy/``) must
    NOT import any LLM SDK or call into ``orchestrator.llm``.

    Per handoff §3.1, autonomy scoring is decision-path code: it
    runs entirely without LLMs. If the module ever calls one,
    Principle 11 (no ground truth → drift) is violated at the
    most load-bearing place in the system.

    The autonomy module does not exist yet (P1.1 is the LLM layer;
    autonomy lands in a later PR). This test runs vacuously now to
    lock the rule **before** the violation has a chance to land —
    so when autonomy implementation begins, the test is already
    standing guard.
    """
    autonomy_dir = SRC_ROOT / "orchestrator" / "autonomy"

    if not autonomy_dir.is_dir():
        # Module not yet created. Test passes vacuously; it will start
        # checking real files the moment autonomy/ exists.
        return

    forbidden_imports = {
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "from orchestrator.llm",
        "import orchestrator.llm",
    }

    violations: list[str] = []
    for py_path in autonomy_dir.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            content = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = py_path.relative_to(SRC_ROOT)
        for pattern in forbidden_imports:
            if pattern in content:
                violations.append(f"  {rel}: {pattern!r}")

    assert not violations, (
        "autonomy module has LLM dependencies (per handoff §3.1, "
        "autonomy is decision-path code and must not call LLMs):\n" + "\n".join(violations)
    )
