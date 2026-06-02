"""Global LLM override — deterministic chain transform (Layer-4).

ADR-023 D2: a pure function that filters + reorders the candidate chain
[default_model, *fallback_chain] before the router walks it. Zero LLM
calls, zero I/O — only static ModelProfile attributes.

Constitutional guarantee (D3): no provider.call(), no routing LLMPurpose.
"""

from __future__ import annotations

from orchestrator.llm.router import ModelRegistry
from orchestrator.llm.types import GlobalLLMOverride, ModelId


def apply_global_override(
    chain: list[ModelId],
    override: GlobalLLMOverride | None,
    models: ModelRegistry,
) -> tuple[list[ModelId], dict[ModelId, str]]:
    """Pure function. Deterministically filters + reorders the candidate
    chain per the global override. Zero LLM calls, zero I/O.

    Returns ``(effective_chain, drop_reasons)`` where ``drop_reasons``
    maps each pre-filtered ``ModelId`` to a human-readable reason string.
    The caller (router) converts ``drop_reasons`` to ``RouteCandidate``
    trace entries with ``accepted=False``.

    None override (or absent file) => returns chain unchanged with empty
    drop_reasons.
    """
    if override is None:
        return list(chain), {}

    drop_reasons: dict[ModelId, str] = {}
    kept: list[ModelId] = []

    # ---- Filter step (cost ceiling) ------------------------------------
    ceiling = override.cost_ceiling_per_1m_output
    if ceiling is not None:
        for model_id in chain:
            profile = models.get(model_id)
            if profile is None:
                # Unknown to registry — keep; the router will record
                # "model not in registry" when it walks the effective chain.
                kept.append(model_id)
                continue

            cost = profile.cost_per_1m_output
            if cost is None:
                # Unknown-cost model: apply on_unknown_cost policy.
                if override.on_unknown_cost == "drop":
                    drop_reasons[model_id] = (
                        f"global override: unknown cost (cost_per_1m_output=None) "
                        f"dropped by on_unknown_cost='drop' "
                        f"(ceiling={ceiling})"
                    )
                else:
                    # "keep" (default): retain but record trace note.
                    # The router will add a separate note via drop_reasons
                    # only for truly dropped models; "kept with unknown cost"
                    # is visible in the chain itself (not dropped).
                    kept.append(model_id)
            elif cost > ceiling:
                drop_reasons[model_id] = (
                    f"global override: cost_per_1m_output={cost} exceeds ceiling={ceiling}"
                )
            else:
                kept.append(model_id)
    else:
        kept = list(chain)

    # ---- Also emit trace entries for unknown-cost models kept under a ceiling,
    # so the router can record their "unknown cost kept" status.
    # We communicate this via a special prefix in drop_reasons only for dropped ones;
    # kept unknown-cost models are visible purely through the effective chain.
    # (Trace entries for kept-unknown-cost are added by the router separately.)

    # ---- Reorder step --------------------------------------------------
    tier = override.quality_tier
    if tier == "economy":
        # Cheapest-first; models with None cost sort LAST.
        def _economy_key(mid: ModelId) -> tuple[int, float]:
            p = models.get(mid)
            if p is None or p.cost_per_1m_output is None:
                return (1, 0.0)  # sort after known-cost models
            return (0, p.cost_per_1m_output)

        kept = sorted(kept, key=_economy_key)

    elif tier == "premium":
        # Most-capable-first (descending capability count); stable sort.
        def _premium_key(mid: ModelId) -> int:
            p = models.get(mid)
            if p is None:
                return 0
            return len(p.capabilities)

        kept = sorted(kept, key=_premium_key, reverse=True)

    # "balanced" and None => identity (no reorder).

    return kept, drop_reasons
