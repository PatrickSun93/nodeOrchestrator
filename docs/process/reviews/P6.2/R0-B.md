---
task_id: P6.2
round: R0-B
verdict: needs_architect
findings_count:
  red: 0
  yellow: 3
  green: 6
reviewed_commit: 5838ce3
reviewed_branch: origin/claude/P6.2-impl
surface: product
lens: runtime-integration + failure-mode (cross-family)
---

# P6.2 R0-B — cross-family review (runtime-integration lens)

## Lens preamble

This review applies the runtime-integration + failure-mode lens per
`docs/process/dual-lens-r0b.md`. The D1 atom touches the LLM fallback-audit
boundary the agy-cli review just hardened — exactly the surface where a
non-Claude lens earns its keep. Focus: transient→fallback cycle correctness
under restart/concurrency/partial failure; permanent-not-fallback;
all-transient exhaustion not swallowing errors; `model_id_requested` ≠
`model_id_used` audit invariant; no double-actuation; health-check pre-filter
vs call-time fallback boundary. C1 also checked for empty-args edge cases.

Gates: ruff clean, mypy clean (310 sources), pytest 2516 passed (0 new
failures). Constitution tests (82/82, including
`test_constitution_override_path_makes_no_llm_call` and all
`select_model_and_provider`-absent structural tests) pass. Spine byte-frozen:
`_execute_local_call` + gate 0-diff. No new `LLMPurpose`.

## Findings

### D1 — call-time transient fallback

| ID | Sev | File/Line | Claim | Suggested investigation |
|---|---|---|---|---|
| R0B-D1-1 | 🟡 | `router.py:110-287` vs `router.py:290-438` | **Code duplication: ~140 lines of per-candidate filter logic duplicated verbatim** between `select_model_and_provider` and `select_viable_routes`. The plan explicitly allowed either factoring (shared helper or delegation to `select_viable_routes(...)[0]`); junior chose neither. Duplicated routing logic is a maintenance hazard — a filter fix in one function leaves the other as a ticking time bomb. | Architect: route α/β/γ. Could factor into a private `_evaluate_candidates(chain, ...) -> (list[RouteCandidate], list[RouteResult])` shared by both, or have `select_model_and_provider` delegate to `select_viable_routes(...)[0]`. Not blocking — plan authorized this choice — but worth a W-N follow-up. |
| R0B-D1-2 | 🟡 | `router.py:290-438` (`select_viable_routes`, `health_check()` calls in filter loop) | **Eager health_check on all chain providers changes runtime behavior.** `select_model_and_provider` health-checks lazily (stops at first viable); `select_viable_routes` health-checks every provider in the effective chain up-front. If `health_check()` is expensive (network probe) or has side effects, this is O(N) for what was O(1) in the common case. Additionally, if a fallback provider's `health_check()` raises (not returns False), it kills the primary — the primary was viable but never reached. D-mech-A explicitly chose this trade-off; the plan documented it. Not a bug, but the runtime cost-profile change should be visible to the architect. | Architect: confirm the trade-off is acceptable. If `health_check()` is a cheap boolean (subprocess-alive check, in-memory flag), the O(N) cost is negligible and this is 🟢 in practice. |
| R0B-D1-3 | 🟡 | `api/llm_adapter.py:86-99` (adapter loop, `call_trace` discarded on success) | **Call-time transient trace discarded on successful fallback.** When the fallback answers, the `call_trace` list (recording the primary's transient failure + reason) is silently discarded — only `LLMResponse.model_id_requested != model_id_used` indicates fallback occurred. The REASON for fallback (rate limit? timeout? 5xx?) is lost to the audit log. The plan explicitly scoped enriching the non-exhaustion trace out of scope. | Architect: note the observability gap for a future cycle. The `LLMResponse` has both IDs; adding a `fallback_reason: str | None` field (or attaching the call_trace to the response) would close this gap without touching the spine. |

### D1 — invariants verified (🟢)

| ID | Sev | What was checked | Result |
|---|---|---|---|
| R0B-D1-4 | 🟢 | No double-actuation | `TransientProviderError` from `provider.call()` means no `LLMResponse` was produced → no `tool_calls` → nothing actuated. Tool execution is downstream of the LLM response (`_execute_local_call`), never inside `call()`. Retrying on the next provider is safe. ADR-003 (`can_use_orchestrator_tools()=False` for CLI providers) is the backstop. |
| R0B-D1-5 | 🟢 | `model_id_requested` ≠ `model_id_used` audit invariant | Every `RouteResult.model_id_requested` is `agent_config.default_model` (chain head). The adapter passes it through to `provider.call()`. On fallback success, `response.model_id_requested(head) != response.model_id_used(fallback)` — the agy-hardened audit contract holds on the call-time path. Verified by `test_transient_primary_falls_to_fallback` asserting both fields. |
| R0B-D1-6 | 🟢 | `PermanentProviderError` propagates, no fallback | The adapter loop only catches `TransientProviderError`; `PermanentProviderError` propagates via normal exception flow. Verified by `test_permanent_primary_propagates_no_fallback` asserting propagation + `fallback.calls == []`. |
| R0B-D1-7 | 🟢 | All-transient → `NoSuitableModelError` + trace | Every viable route raises `TransientProviderError` → `NoSuitableModelError` with `decision_trace` listing one entry per attempted route (`model_id`, `provider_id`, `accepted: False`, `reason: "call-time transient: …"`). Shape matches the existing exhaustion raise at `router.py:284`. Verified by `test_all_transient_raises_no_suitable_model_error`. |
| R0B-D1-8 | 🟢 | Router purity preserved | `select_viable_routes` makes zero `provider.call()` (health_check only). The `.call()` loop lives in the adapter. Constitution tests (`test_constitution_override_path_makes_no_llm_call` + all `select_model_and_provider`-absent structural tests) pass unchanged. |
| R0B-D1-9 | 🟢 | ADR-002 D4 amendment note | Style/weight matches existing `2026-06-11 (agy-cli-provider)` and `2026-06-02 (P2.7 / ADR-023)` notes. Records (i) call-time half implemented, (ii) safe because `provider.call()` is side-effect-free content-gen. No Accept gate (`plan_has_adr=false`). |

### C1 — empty tool-args normalization

| ID | Sev | What was checked | Result |
|---|---|---|---|
| R0B-C1-1 | 🟢 | Edge cases: `""`, `"   "`, `None`, `{}`, `"{bad"`, missing key, `"\t"`, `"\n"` | `strip()` guard correctly normalizes empty/blank → `{}`. `None`/falsy non-str → `{}` (preserved). Malformed JSON → `PermanentProviderError` (preserved). Missing key → `KeyError` → `PermanentProviderError` (preserved, per ratified scope boundary). `"null"` → `json.loads("null")` → `None` → Pydantic `ValidationError` → `PermanentProviderError` (correct — `null` is not a dict). Fail-on-revert tests (`test_empty_string_arguments_normalizes_to_empty_dict`, `test_blank_string_arguments_normalizes_to_empty_dict`, `test_malformed_json_arguments_still_raises_permanent`) all pass. |

## Synthesis

No 🔴 findings. The implementation is correct and conforms to the senior plan
on all acceptance criteria. The three 🟡 findings cluster around two themes:

1. **Maintenance hazard** (R0B-D1-1): the duplicated filter chain is a future
   bug factory. The plan authorized this factoring choice, so it's not a
   defect — but the architect should decide whether to address it now or
   defer.

2. **Runtime observability** (R0B-D1-2, R0B-D1-3): the eager health_check
   changes the cost profile, and the successful-fallback path discards the
   primary's failure reason. Both were explicitly scoped in the plan
   (D-mech-A trade-off; trace enrichment out of scope). Flagging so the
   architect has visibility for future cycles.

The cross-family lens did not surface any 🔴-class runtime-integration bugs
of the kind found in P1.4 (missing failure paths, indistinguishable error
modes). The D1 implementation is defensively sound: the loop handles
transient→next, permanent→propagate, and all-transient→exhaustion correctly;
the audit invariant holds; and the double-actuation argument is grounded in
the constitutional spine, not in developer optimism.

## Gates verification

| Gate | Result |
|---|---|
| ruff | Clean |
| mypy (`files = src,tests`) | Clean (310 sources) |
| pytest (full) | 2516 passed, 0 failed |
| Constitution tests | 82/82 passed |
| `LLMPurpose` grep | No new values |
| Spine diff | `_execute_local_call` + gate 0-diff |
