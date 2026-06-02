---
task_id: P2.7
round: R0-B-cross-family
reviewer_family: deepseek
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 8
verdict_history:
  - verdict: needs_architect
    at_commit: b564633
    findings_count: { red: 0, yellow: 2, green: 6 }
    note: initial R0-B-cross-family (deepseek). S2 override IS genuinely deterministic code (spy + AST guard structurally enforce c1; composes with Layer-3 no bypass); S3 allowlist IS fail-closed for the config path. Two 🟡 — Y1 (S2 cost_ceiling "keep on unknown" = unpriced models bypass the cost dial; no trace visibility) + Y2 (S3 subprocess-env inheritance: unset base_url may NOT be fail-closed if parent carries ANTHROPIC_BASE_URL — the sharpest c2 probe). Both resolvable at plan stage; lean α on both.
  - verdict: clean
    at_commit: PENDING-plan-stage-routing-absorption
    findings_count: { red: 0, yellow: 0, green: 8 }
    note: >-
      Bumped per architect plan-stage routing + RC-10 + dual-lens Step 5. Y1 → α (convergent
      with R0-A Y1): `on_unknown_cost: Literal["keep","drop"] = "keep"` knob + a decision_trace
      entry for every unknown-cost model met under a ceiling (visibility in both modes) —
      ADR-023 D1/D2 + plan §2-S2. Y2 → α MUST-FIX (the cross-family security catch): ADR-023 D4
      + plan §2-S3 now pin the subprocess-env contract — when base_url is None the child env has
      ANTHROPIC_BASE_URL **explicitly cleared** (a parent value is dropped, never forwarded), so
      the redirect can take effect only through the allowlisted path; + a discriminating test
      (parent ANTHROPIC_BASE_URL=untrusted + config base_url=None → child does NOT receive it),
      plan §2-S3 AC#2b. This closes the inheritance bypass without changing the allowlist/config
      contract — exactly this review's α lean. Both 🟡 → 🟢 (8🟢). Did NOT accept ADR or advance state.
---

# P2.7 R0-B cross-family review (plan + ADR-023) — LLM Layer-4 override + alt-backend + startup

| Field | Value |
|---|---|
| Round | R0-B-cross-family (true cross-family, plan-stage; S2 routing-is-code + S3 security-boundary lens) |
| Reviewer family | deepseek |
| Stage | Plan + ADR-023 (Proposed) + ADR-002/ADR-012 amendments, pre-impl |
| Artifacts | `senior-plans/P2.7.md`, `ADR-023-llm-layer4-override-altbackend-startup.md`, ADR-002 amendment, ADR-012 amendment |
| Baseline | `main` — `router.py:15` ("zero LLM calls"), `router.py:109` (select_model_and_provider), `openai_compatible.py:64` (base_url precedent), `claude_code_cli.py` (no base_url), `state_machine.py:219-231` (_next_scaffold_state returns None) |
| Prior reviews | None yet (R0-A-on-plan pending) |
| Date | 2026-06-02 |
| Verdict | **clean** (bumped from needs_architect) — 0🔴 · 0🟡 · 8🟢 |

> **Routing-absorption note (RC-10 + dual-lens Step 5).** Both 🟡 routed **α** — exactly this review's leans. **Y1** (S2 soft-ceiling, convergent with R0-A Y1): `on_unknown_cost: Literal["keep","drop"]="keep"` + a `decision_trace` entry for unknown-cost models met under a ceiling, in both modes (ADR-023 D1/D2). **Y2** (MUST-FIX, the cross-family security catch — the subprocess-env-inheritance bypass): ADR-023 D4 + plan §2-S3 now pin the subprocess-env contract — `base_url=None` ⇒ child `ANTHROPIC_BASE_URL` **explicitly cleared** (parent value dropped, never forwarded) + a discriminating test (parent `ANTHROPIC_BASE_URL=untrusted` + config `base_url=None` → child does not receive it). Both 🟡 → 🟢. Original findings preserved below for the audit trail.

## Lens preamble

Cross-family S2 routing-is-code + S3 security-boundary lens per `external-r0b-prompt.md` probes. S2 is a routing decision — the sharpest Principle-5 test since P2.3: *does a "quality_tier" config knob stay deterministic code, or does it smuggle LLM judgment into model selection?* S3 is a trust boundary — the first time conversation content + API keys flow to a third-party backend: *is fail-closed genuinely fail-closed, including the subprocess-env-inheritance angle?* S1 (room-SM pattern-reuse) and S4 (error polish) are single-lens territory per the dispatch scope; this review focuses on S2 + S3. Over-correcting for Claude biases: sycophancy toward "airtight" / "composes" / "fail-closed" claims without tracing the actual failure paths, and toward the plan's confidence that the structural test + AST guard closes all S2 holes and the allowlist closes all S3 holes.

## Findings

| # | Sev | Finding | Evidence |
|---|---|---|---|
| Y1 | 🟡 | **S2 cost_ceiling "keep on unknown" — unpriced models bypass the cost-governance dial.** ADR-023 D2: a candidate with `cost_per_1m_output is None` is **kept** when a cost ceiling is set ("the ceiling cannot be evaluated, so the override does not silently drop it"). This means an unpriced model at $50/1M output would still be selected under `cost_ceiling_per_1m_output=5`. The user sets a cost ceiling thinking they're capping spend; unknown-cost models silently evade it. The ADR frames the alternative (fail-closed on unknown cost) as "surprising for a cost dial" — but the current default is MORE surprising: a cost-governance knob that doesn't govern costs when pricing data is absent. The `decision_trace` extends with the override-filter reason for dropped models, but there is no trace entry for "N models skipped due to unknown cost" — the user has no visibility into which models bypassed the ceiling via unknown pricing. Cross-family assessment: "keep on unknown" is the wrong default for a cost-governance surface. At minimum, the `decision_trace` should note unknown-cost models so the user is informed; ideally, the policy should be configurable (keep/drop on unknown) or default to drop-with-warning. | ADR-023 D2 ("kept — the ceiling cannot be evaluated"); ADR-023 D2 (empty-chain → NoSuitableModelError with override filter reason — but no unknown-cost tracing) |
| Y2 | 🟡 | **S3 subprocess env inheritance — unset `base_url` may NOT be fail-closed if the parent process carries `ANTHROPIC_BASE_URL`.** ADR-023 D4: "When set, the provider passes `ANTHROPIC_BASE_URL=<base_url>` in the subprocess environment." But neither the plan nor ADR addresses what happens when `base_url` is **unset** (`None` — the safe default). The Claude Code provider shells out to the `claude` CLI via subprocess. If the subprocess inherits the parent process's environment (the Python default for `subprocess.run` with `env=None`), a parent-process `ANTHROPIC_BASE_URL` — set by the OS, a wrapper script, a container runtime, or a prior subprocess invocation — would be inherited by the child Claude Code process, routing conversation content + API keys to an untrusted backend **without passing through the allowlist**. The entire c2 security boundary (opt-in + allowlist) is silently bypassed. This is the sharpest S3 probe from the external prompt: *"does an UNSET config still let a parent-process ANTHROPIC_BASE_URL leak through to the child uncontrolled?"* The fix is simple but must be explicit: when `base_url` is `None`, the subprocess env must explicitly **unset** or **clear** `ANTHROPIC_BASE_URL` (e.g., `env = {**os.environ, "ANTHROPIC_BASE_URL": ""}` or constructing a clean env with only explicit vars). The plan should address this; the ADR should state the subprocess-env contract. | ADR-023 D4 (subprocess env when set, silent on unset); `claude_code_cli.py` (shells out to `claude` binary via subprocess — current behavior unknown); external-r0b-prompt §35-ii (explicitly asks about subprocess-env inheritance) |
| G1 | 🟢 | **S2 override IS genuinely deterministic code — quality_tier does not smuggle judgment.** The override is a pure chain transform: `quality_tier` → stable sort over static `ModelProfile` attributes (cost, capability count); `cost_ceiling` → filter over static `cost_per_1m_output`. No LLM call, no inference, no non-deterministic signal. The structural test (spy provider `call` count == 0 across every tier/ceiling combination + AST guard) is genuine — the spy proves no runtime LLM call, the AST guard proves no code reference to provider `.call`. The `LLMPurpose` taxonomy stays content-gen-only (no new purpose added — verified the project has no routing purpose). Cross-family trace: no path where a quality-tier selection decision reaches an LLM. The "slippery slope" concern (a future tier value implemented as LLM-scored) is defended by the structural test — any LLM call in the selection path trips the spy regardless of tier value. | ADR-023 D2 (pure chain transform), D3 (structural test + AST guard); `router.py:15` ("zero LLM calls"); `purposes.py` (all content-gen) |
| G2 | 🟢 | **S2 override genuinely composes with Layer-3 — never bypasses capability/health filters.** The chain transform filters and reorders BEFORE the router walks the chain. The router's existing `required_capabilities` + provider-exists + tools-support + `health_check` per-candidate checks still run — unchanged. The override cannot select a capability-missing or unhealthy model because the router's per-candidate loop rejects it regardless of chain position. Empty chain (all candidates filtered by override) → `NoSuitableModelError` with the override reason in `decision_trace` — fail-loud, never a silent fallback to unfiltered. Cross-family trace: the composition claim holds — the override pre-filters, the router still guards. | ADR-023 D2 (chain transform before router walk, empty-chain fail-loud); ADR-002 D4 (Layer-3 filters unchanged) |
| G3 | 🟢 | **S3 allowlist IS fail-closed for the config path.** `base_url` set and ∉ `trusted_base_urls` → `ConfigError` at startup (including empty allowlist). `base_url` unset → no validation, Anthropic default. The allowlist is co-located with the opt-in (`trusted_base_urls` in the same provider config as `base_url`) — the trust grant is declared next to the redirect it authorizes. Credentials use the existing `api_key_env` indirection (never inline). The trust tier is explicitly documented as higher than the local r0b proxy. Cross-family trace: the config-path security boundary holds — the allowlist correctly gates the sanctioned configuration path. The subprocess-env-inheritance bypass (Y2) is the only hole found. | ADR-023 D5 (fail-closed allowlist, ConfigError on untrusted), D6 (credentials + trust tier); D4 (opt-in, unset = default) |
| G4 | 🟢 | **S2 structural test is discriminating, not vacuous.** The spy provider test drives `apply_global_override` + `select_model_and_provider` across every `quality_tier`/`cost_ceiling` combination and asserts `provider.call` count == 0. This IS discriminating: it proves the negative (no LLM call) across the full combinatorial space, not just one happy path. The AST guard checks the code path. Combined, they catch both runtime calls and code references. An LLM call added to the selection path (e.g., a future "smart_reorder" tier) would trip the spy — the test would fail before the PR lands. The discriminating assertion (call count == 0, not "call count unchanged") is the right shape. | ADR-023 D3 (spy provider + AST guard); plan S2 AC#1 (RC-24 structural test + RC-25 discriminating) |
| G5 | 🟢 | **S1 room-SM scaffold + S4 startup errors are correctly scoped; split recommendation is sound.** S1: `_next_scaffold_state` returns `None` on `main` (verified `state_machine.py:219-231`) — S1 fills the always-None stub. Pattern-reuse from `_next_research_state`, pure code, no LLM. S4: `bootstrap.py` is the pinned boot home; `render_startup_error` renders actionable messages from existing `ConfigError.violations` + `NoSuitableModelError.decision_trace` + `ProviderHealth.error`. The split recommendation (4 sub-slice tasks, P2.7d last) correctly sequences around the `config_loader.py` co-edit between S2 and S4. S1 (`rooms/`) ∥ S2 ∥ S3 (`providers/`) are genuinely file-disjoint. The amendments (ADR-002 4th layer, ADR-012 scaffold tables) are RC-23-safe (no literal Status-value substring in amendment prose). | `state_machine.py:219-231` (_next_scaffold_state → None); plan §3 (file-boundary truth + split graph); ADR-023 D7/D8 (bootstrap + render) |
| G6 | 🟢 | **No new `LLMPurpose` — the taxonomy stays content-gen-only.** S2 adds zero routing/judgment purposes (verified: `purposes.py` all content-gen through P2.6; the plan's §7 self-discovery confirms no routing purpose exists or is added). The override is a list transform over static config — no inference surface. The c1 guarantee is structurally enforced by the spy test + AST guard (G1/G4), not by `LLMPurpose` taxonomy discipline alone. | Plan §4 Q1 (no new LLMPurpose); `purposes.py` (all content-gen); ADR-023 D3 (no new purpose) |

## Synthesis

The design is sound on the major calls. S2's override IS genuinely deterministic code — the spy test + AST guard structurally enforce the c1 boundary, and the chain-transform composes with Layer-3 without bypass. S3's allowlist IS fail-closed for the config path — opt-in + explicit trust grant + `ConfigError` on untrusted URL.

Two 🟡 from the cross-family lens, one per surface:

**Y1 (S2):** The cost_ceiling "keep on unknown" policy is the wrong default for a cost-governance dial. A user setting `cost_ceiling=5` expects to cap costs; an unpriced model at $50/1M silently bypasses the ceiling. At minimum, the `decision_trace` should note which models were skipped due to unknown cost. Ideally, the policy should be configurable (keep/drop/warn on unknown).

**Y2 (S3):** The subprocess-env-inheritance angle is the sharpest S3 probe and it is not addressed. If the parent process carries `ANTHROPIC_BASE_URL` (from OS env, wrapper script, or container runtime) and `base_url` is unset, the child Claude Code subprocess would inherit it — routing traffic to an untrusted backend without passing through the allowlist. The fix is simple (explicitly clear/unset `ANTHROPIC_BASE_URL` in the subprocess env when `base_url` is `None`) but must be explicit in both the plan and ADR.

Both are resolvable at plan stage — small spec adjustments, no design changes.

## What the architect needs to route

1. **Y1 (🟡):** S2 cost_ceiling "keep on unknown" — unpriced models silently bypass cost-governance. Lean: **α** — add a `decision_trace` entry noting "N models with unknown cost skipped ceiling check" so the user has visibility; consider making the policy configurable (`on_unknown_cost: Literal["keep", "drop"]` with default `keep`). Alternatively, **β** — accept "keep on unknown" as documented (the ADR already states it), but add the trace entry. Alternatively, **γ** — change the default to drop-on-unknown (fail-closed for cost governance — but this could silently break deployments where sentinel/free models have `None` cost).
2. **Y2 (🟡):** S3 subprocess env inheritance — unset `base_url` may not be fail-closed if parent carries `ANTHROPIC_BASE_URL`. Lean: **α** — explicitly address in ADR-023 D4: when `base_url` is `None`, the subprocess env must explicitly unset/clear `ANTHROPIC_BASE_URL` (e.g., construct env with `ANTHROPIC_BASE_URL` excluded or set to empty). This closes the inheritance bypass without changing the allowlist or config contract. Add a discriminating test: parent env has `ANTHROPIC_BASE_URL=untrusted`, config has `base_url: None` → child process does NOT receive `ANTHROPIC_BASE_URL`.
3. **Greens** are cross-family confirmations; no action.
