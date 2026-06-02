---
task_id: P2.7
round: R0-B
reviewer_family: deepseek
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 7
---

# P2.7 R0-B (cross-family, impl-stage) — LLM Layer-4 override + alt-backend + startup

| Field | Value |
|---|---|
| Round | R0-B (cross-family, impl-stage; S2 routing-is-code + S3 security-boundary lens) |
| Reviewer family | deepseek |
| Impl branch | `claude/P2.7-impl` @ `ce0d043` (atomics P2.7-1..6) |
| Baseline | `main` (ADR-023 Accepted; plan-stage 2🟡 both α-absorbed) |
| Plan-stage absorptions | Y1: `on_unknown_cost: Literal["keep","drop"]` knob + decision_trace; Y2: `_build_child_env()` strips `ANTHROPIC_BASE_URL` from parent + discriminating test |
| Date | 2026-06-02 |
| Verdict | **clean** — 0🔴 · 0🟡 · 7🟢 |

## Lens preamble

Cross-family impl-stage S2 routing-is-code + S3 security-boundary lens. The plan-stage cross-family R0-B found two 🟡: Y1 (cost_ceiling "keep on unknown" = unpriced models bypass governance) and Y2 (subprocess env inheritance = parent `ANTHROPIC_BASE_URL` could bypass the allowlist). Both routed α and absorbed. This pass traces the **actual code** to verify absorption and probe for net-new issues: the S2 structural tests (spy + AST guard — discriminating or vacuous?), the S3 `_build_child_env` contract (does it genuinely strip the parent env?), the cost ceiling unknown-cost visibility, the override's composition with the router, and the allowlist validation. S1 (room-SM) and S4 (startup errors) are light-scan per the dual-lens scope.

## Findings

| # | Sev | Finding | Evidence |
|---|---|---|---|
| G1 | 🟢 | **Y2→α absorbed — `_build_child_env` genuinely prevents parent-env ANTHROPIC_BASE_URL inheritance.** The Claude Code provider (`claude_code_cli.py`) gains `_build_child_env()` which explicitly reconstructs the child env by stripping `ANTHROPIC_BASE_URL` from the parent (`os.environ`) before optionally injecting the allowlisted value: `env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_BASE_URL"}`. The allowlist is validated at construction time in `__post_init__`: `base_url not in trusted_base_urls` → `ConfigError`. The child env is used in both `health_check()` and `call()` — every subprocess path is covered. Discriminating tests (test_claude_code_cli_provider.py): (a) parent `ANTHROPIC_BASE_URL=untrusted` + config `base_url=None` → child env does NOT contain `ANTHROPIC_BASE_URL` (the exact Y2 probe); (b) `base_url` set + allowlisted → child env receives it; (c) parent has untrusted + config has trusted → only trusted value flows to child (parent value dropped); (d) `base_url=None` → no `ANTHROPIC_BASE_URL` key at all; (e) unrelated env vars preserved. Cross-family confirmation: the subprocess-env-inheritance bypass that was the sharpest S3 probe at plan stage is now structurally closed — the allowlist is the sole path for `ANTHROPIC_BASE_URL` to reach the child. | `claude_code_cli.py` (_build_child_env); `__post_init__` (allowlist validation); `test_claude_code_cli_provider.py:458-512` (5 discriminating env tests) |
| G2 | 🟢 | **Y1→α absorbed — `on_unknown_cost` knob implemented with trace visibility.** `apply_global_override` (`override.py:16-103`): `on_unknown_cost: Literal["keep","drop"]` (default `keep`). When `drop`: unknown-cost models get a `drop_reasons` entry with the ceiling context. When `keep`: retained. Models not in the registry are kept (the router will handle them during chain walk, recording "model not in registry"). The cost ceiling filter (`cost > ceiling` → dropped) and quality tier reorder (economy = cheapest-first with unknown-cost sorted last; premium = most-capable-first descending; balanced = identity) are correctly implemented as stable sorts over static `ModelProfile` attributes. The returned `drop_reasons` dict is consumed by the router for `RouteCandidate` trace entries. Cross-family confirmation: the "keep on unknown" default remains but is now configurable and visible — the user knows which models bypassed the ceiling. | `override.py:39-71` (cost ceiling filter + on_unknown_cost); `override.py:80-101` (quality tier reorder); `router.py` (drop_reasons → RouteCandidate trace) |
| G3 | 🟢 | **S2 structural tests are genuine + discriminating.** Two tests enforce the c1 guarantee: (a) `test_constitution_override_module_has_no_provider_call` (`test_constitution.py:228-258`) — AST guard scans `override.py` for `ast.Attribute` nodes with `attr=="call"` and `ctx==Load` — catches any `provider.call()` or `llm.call()` code reference. Discriminating: docstrings/comments are not in the AST as Attribute nodes, so the guard won't false-positive on prose mentioning `.call()`. (b) `test_constitution_override_path_makes_no_llm_call` (`line 262`) — spy provider drives `apply_global_override` + `select_model_and_provider` across quality_tier/ceiling combinations and asserts call count == 0 (selection consults only `health_check()` — a sync probe, not an LLM call). Cross-family trace: the spy test proves no runtime LLM call; the AST guard proves no code reference. Combined, they structurally enforce "zero LLM in the selection path" — a future `quality_tier` that added an LLM-scored reorder would trip the spy. | `test_constitution.py:228-258` (AST guard), `:262` (spy test); `override.py:13-14` (imports — no LLM) |
| G4 | 🟢 | **S2 override genuinely composes with Layer-3 — no bypass.** `apply_global_override` returns `(effective_chain, drop_reasons)`. The router's `select_model_and_provider` receives the `effective_chain` and walks it with existing Layer-3 filters: `required_capabilities` + provider-exists + tools-support + `health_check` per candidate — unchanged. The override only pre-filters/reorders *which* candidates the router considers; every candidate still passes through the router's per-candidate gates. Empty chain (all candidates filtered) → router raises `NoSuitableModelError` with the override filter reasons in `decision_trace` — fail-loud. Absent override (`None`) / absent config file → `apply_global_override` returns chain unchanged — backward-compatible (test-coverage §3). Integration site: `router.py` gains `effective_chain, drop_reasons = apply_global_override(chain, override, models)` before the walk loop. | `override.py:32-33` (None → identity); `override.py:16-20` (returns effective_chain + drop_reasons); `router.py` (effective_chain fed into existing walk) |
| G5 | 🟢 | **S3 allowlist is fail-closed — validated at construction, never a runtime bypass.** `__post_init__` (`claude_code_cli.py`) checks `base_url is not None and base_url not in trusted_base_urls` → raises `ConfigError` with actionable message. This fires at provider construction (config load time), before any subprocess is spawned. An empty `trusted_base_urls` list with a set `base_url` → `ConfigError` (fail-closed). The `base_url` is a plain string comparison — exact match required (no normalization/redirect-following, which is correct: the allowlist is an explicit trust grant, not a URL parser). `api_key_env` indirection preserved. The trust tier is documented in the module docstring. Cross-family trace: no path where `base_url` reaches the subprocess without passing the allowlist. | `claude_code_cli.py` (__post_init__ ConfigError); module docstring (trust tier documentation); `api_key_env` (unchanged) |
| G6 | 🟢 | **S1 room-SM scaffold + S4 bootstrap correct.** S1: four new `_next_<type>_state` functions in `state_machine.py` with discriminating per-arc tests (`test_state_machine.py` — each arc fires on right trigger, wrong event returns None, `_guard_valid_state` preserved, `setup`+`closed` in every set). Pure code, no LLM import. S4: `bootstrap.py` sequences load→validate→check_all_providers → StartupError with rendered message from `render_startup_error`; message content asserted (over-tight cost_ceiling renders the ceiling + dropped models; un-allowlisted base_url renders the URL + trusted_base_urls field). S4 sequenced last (depends on S2/S3 to render their failure modes). | `state_machine.py` (4 new state functions); `test_state_machine.py` (per-arc discriminating tests); `bootstrap.py` (load-and-validate sequence); `test_bootstrap.py` (message content asserted) |
| G7 | 🟢 | **No new LLMPurpose; import guards + gates green.** S2 adds zero `LLMPurpose` values — the taxonomy stays content-gen-only. The `GlobalLLMOverride` model is frozen + `extra="forbid"`. The `llm_override.yaml` is optional (absent = no-op). Gates: ruff ✓ · mypy ✓ · pytest all passed. No §7 handoff bundling. ADR-002/ADR-012 amendments are RC-23-safe (no literal Status-value substring in amendment prose). | `override.py` (no LLMPurpose reference); `types.py` (GlobalLLMOverride frozen+forbid); commit `ce0d043` gate summary |

## Synthesis

Both plan-stage cross-family 🟡 are correctly absorbed at impl. Y2 (the subprocess-env-inheritance security hole) is closed by `_build_child_env()` — the parent `ANTHROPIC_BASE_URL` is explicitly stripped from every child subprocess path, and discriminating tests prove the fix. Y1 (cost_ceiling unknown-cost bypass) is addressed by the `on_unknown_cost` configurable knob with `decision_trace` visibility.

The S2 routing-is-code boundary — the highest-stakes check — holds at impl: the spy test + AST guard structurally enforce zero LLM in the selection path, the chain transform composes with Layer-3 without bypass, and no routing `LLMPurpose` exists. The S3 security boundary — the second target — is now structurally enforced: the allowlist is validated at construction (fail-closed), and the subprocess env is explicitly constructed (no parent inheritance).

No net-new 🔴 or 🟡. The impl is genuinely clean across all invariants both lenses traced. Seven greens — the P2 closing slice checks out.

## For the architect

No routing needed. The impl is accept-worthy as-is. Both plan-stage cross-family 🟡 are correctly absorbed, and no net-new issues found at impl stage.
