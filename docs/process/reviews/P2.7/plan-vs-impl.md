---
task_id: P2.7
round: plan-vs-impl
reviewer: senior
impl_commit: ce0d043
verdict: needs_architect
verdict_history:
  - verdict: needs_architect
    at_commit: ce0d043
    findings_count: { red: 0, yellow: 1, green: 6 }
    note: >-
      initial plan-vs-impl. S1 (4 RoomType transition tables) byte-faithful to the ADR-012
      amendment + thoroughly discriminating (per-state wrong-event negatives + full-chain per
      type); S2 c1 solid (apply_global_override pure fn; AST guard + spy call==0 across 7 combos;
      composes with Layer-3; empty-chain fail-loud; no new routing LLMPurpose); S3 fully faithful
      + discriminating (allowlist fail-closed + the Y2-α env-clear wired into both subprocess
      paths with the exact AC#2b parent-inheritance test + extra anti-leak tests); S4 bootstrap +
      StartupError + render_startup_error message-content tests (§4) + ConfigError→StartupError
      boundary; batched landed (7 commits per the atomic graph); amendments RC-23-safe; gates
      green independently (149 P2.7 tests + ruff + mypy strict). ONE 🟡 — Y1-α keep-mode trace
      visibility is NOT implemented: ADR-023 D2 (Accepted) + plan §2-S2 AC#3b require BOTH modes
      to emit an unknown-cost decision_trace entry, but only drop-mode does; keep-mode (the default
      soft-ceiling — the exact case R0-B Y1 flagged) stays silent, and its test is non-discriminating
      (asserts only acceptance). Flagged, not waved through.
findings_count:
  red: 0
  yellow: 1
  green: 6
---

# P2.7 plan-vs-impl (senior) — 平台演化 + LLM 层 + 启动 polish (P2 closing slice)

| Field | Value |
|---|---|
| Reviewer | senior (plan-vs-deliverable lens) |
| Plan | `docs/process/senior-plans/P2.7.md` (batched §3 + the Y1/Y2 plan-stage absorption) |
| ADR | `ADR-023` (**Accepted**) + `ADR-002`/`ADR-012` amendments (Implemented) |
| Impl | `claude/P2.7-impl` @ `ce0d043` (7 commits: prelude `5946840`, S1 `2df7269`, S2 `167afb7`, S3 `f954973`, integration-fix `0531c93`, S4 `b37ecf7`, e2e/landing `ce0d043`) |
| Verdict | **needs_architect** — 0🔴 · 1🟡 · 6🟢 |

## Summary

A strong implementation of the P2 closing slice — three of the four sub-items are faithful to the plan + ADR-023 + the amendments and discriminatingly tested; the batched structure (decision a) landed as the atomic graph specified; gates are green (I re-ran the P2.7 scope: **149 tests pass, ruff clean, mypy --strict clean**). The constitutional crux holds: S2's `apply_global_override` is a pure chain transform with a real AST guard **and** a spy-provider test asserting `provider.call`==0 across all seven override combinations, it composes with — never bypasses — Layer-3, and no routing `LLMPurpose` is added. The security MUST-FIX holds: S3's `_build_child_env` strips a parent `ANTHROPIC_BASE_URL` and is wired into **both** subprocess paths, with the exact parent-inheritance discriminating test the plan named.

**One 🟡 — a real deviation from the now-Accepted ADR-023 D2 + plan §2-S2 AC#3b:** the **Y1-α keep-mode unknown-cost trace visibility is not implemented**. The ADR requires *both* policies to make the softness visible ("kept-despite-unknown-cost, or dropped-as-unknown-cost"); the impl delivers only the **drop** path. **Keep** (the *default* soft-ceiling — the precise case R0-B's Y1 raised) leaves no distinct trace entry, and its test is **non-discriminating** (asserts only that the model is accepted). Surfaced below; not constitutional, not blocking, but a genuine plan/ADR deviation the architect should route.

## Per-sub-item verification

| Sub-item | Delivered | Plan/ADR match | Evidence |
|---|---|---|---|
| **S1** room-SM scaffolds | ✓ `2df7269` | ✓ **faithful** | `state_machine.py:91-94` — BugFix/CodeReview/IdeaValidation 5-state + FreeChat 3-state **exactly** the ADR-012 amendment sets; four `_next_<type>_state` fns (`:249/313/377/441`) with `rule_matched` strings **byte-identical** to the amendment table; per-type `match`/`case` dispatch (`:539-547`) replacing the always-`None` scaffold; `_VALID_STATES` updated; pure code (no `llm/` import). Tests: per-state **wrong-event-returns-None** negatives for every state of all 4 types (`:335-604`) + **full-chain** per type (`:779-854`) — discriminating, `setup`+`closed` preserved. |
| **S2** Layer-4 override (c1) | ◑ `167afb7` | **mostly** — see Y1 | `override.py::apply_global_override` pure fn over static `ModelProfile` attrs (cost filter + tier stable-reorder, D2); **c1 enforced**: `test_constitution_override_module_has_no_provider_call` (AST) + `test_constitution_override_path_makes_no_llm_call` (spy, `call`==0 across 7 combos) — discriminating; **composes** (router walks `effective_chain` through capability/provider/tools/health, `router.py:196-268`); **empty-chain → `NoSuitableModelError`** fail-loud (`:190-194`); **no new routing `LLMPurpose`** (`test_constitution_no_new_llm_purpose_in_p27`); `on_unknown_cost` knob present. **Y1: keep-mode trace visibility missing (finding).** |
| **S3** alt-backend (c2) | ✓ `f954973` | ✓ **faithful** | `claude_code_cli.py` — `base_url: str\|None=None` opt-in + `trusted_base_urls`; `__post_init__` fail-closed `ConfigError` (`:98-109`, D5); **Y2-α** `_build_child_env` strips parent `ANTHROPIC_BASE_URL` (`:119`) + injects only if set, **wired into both** `subprocess.run` (`:146`) and `create_subprocess_exec` (`:231`); `api_key_env` indirection. Tests: allowlist accept/reject/empty (`:390-414`), **the AC#2b parent-inheritance test** `test_child_env_clears_anthropic_base_url_when_base_url_none` (`:458`), anti-leak-when-allowlisted (`:478`), message-content (`:429-454`) — all discriminating. |
| **S4** bootstrap + errors | ✓ `b37ecf7` | ✓ **faithful** | `bootstrap.py::load_and_validate_llm_layer` sequences load_providers→models→agents→**override**→validate→health (composes existing loaders, D7); `StartupError(LLMError)` (`exceptions.py:94`); `render_startup_error` renders `ConfigError.violations` + `NoSuitableModelError.decision_trace` + **S2/S3 hints** (override + allowlist — D8). Tests: **message-content asserted** (`test_bootstrap.py:215-236`, §4 load-bearing), `ConfigError`→`StartupError` boundary (`:143-205`, §5). |

Batched (decision a) landed: 7 commits per the §3 atomic graph (prelude resolves the shared `config_loader.py`/`types.py` seams; integration-fix `0531c93` removed a duplicate `GlobalLLMOverride`; S4 last). Amendments **RC-23-safe** (flipped `Proposed → "— Implemented (ADR-023 accepted; P2.7 impl)"` — no literal `Status:`-value substring). ADR-023 left **Accepted** (the architect's, not mine).

## Findings

### 🟡 Y1 — S2 keep-mode unknown-cost trace visibility is NOT implemented (deviates from Accepted ADR-023 D2 + plan AC#3b; non-discriminating test masks it)

ADR-023 D2 (**now Accepted**) is explicit: *"Either way the softness is made visible: every unknown-cost candidate encountered under a set ceiling gets a `decision_trace` / `RouteCandidate` entry recording it was skipped-by-the-ceiling-check (**kept-despite-unknown-cost, or dropped-as-unknown-cost**) — so a user reading the route never silently believes an unpriced model was cost-bounded."* Plan §2-S2 AC#3b: *"both emit the unknown-cost decision_trace entry (assert the entry is present in each mode, so the softness is never silent)."*

**The impl does this for `drop` only, not for `keep` (the default):**
- **drop** — `override.py:52-57` records `drop_reasons[model_id]`; `router.py:179-187` emits a rejected `RouteCandidate`. Discriminating test `test_unknown_cost_trace_entry_present_in_drop_mode` (`test_router.py:532`) asserts the entry + `"unknown" in reason`. ✓
- **keep** (default) — `override.py:58-63` keeps the model with **no** `drop_reasons` entry; its comments (`:73-77`) say *"Trace entries for kept-unknown-cost are added by the router separately,"* but `router.py` emits trace entries **only** from `drop_reasons` (dropped models). A kept unknown-cost model flows into the normal walk and appears as a plain `"matched"` entry — there is **no** distinct "kept despite unknown cost under ceiling=X" note. **The softness stays silent in the default mode** — exactly the gap R0-B's Y1 raised ("the user has no visibility into which models bypassed the ceiling via unknown pricing").
- The keep-mode test `test_unknown_cost_trace_entry_present_in_keep_mode` (`test_router.py:556-575`) is **non-discriminating**: it asserts only `any(c.accepted for c in unpriced_entries)` — i.e. the model was selected. That passes regardless of the ceiling or the policy (an unpriced model with no ceiling at all would also be "accepted"). It does **not** assert any unknown-cost-specific trace note, so it does not guard the AC#3b visibility contract. (The P2.7-6 commit body also over-claims *"decision_trace extended by … unknown-cost entries"* — true only for drop.)

**Why it matters:** Y1-α was an *absorbed* routing item (R0-A Y1 + R0-B Y1 convergent), and keep-mode is the default + the very case the finding was about. This isn't constitutional (routing is still code) or blocking (the override works; the model is genuinely kept), but it's a faithful-to-Accepted-ADR gap with a test that masks it.

**Lean (surface, not decide): α** — when a ceiling is set and a kept candidate has unknown cost, `apply_global_override` should also surface it (e.g. return a `kept_unknown` set, or an `accepted=True` `RouteCandidate` carrying a "kept despite unknown cost (ceiling=X)" reason); `render_startup_error`/the trace then shows it; **make the keep-mode test discriminating** (assert the unknown-cost note is present, not just acceptance). Small, localized to `override.py` + `router.py` + the one test. **Or β** — accept "kept models are visible via the effective chain itself" as sufficient and **amend ADR-023 D2** to say keep-mode visibility is the chain, not a trace entry (closing the doc-vs-impl gap the other direction) — but that re-opens an Accepted ADR. Architect's call (it touches the Accepted-ADR contract).

## What holds — verified clean (G1–G6)

- **G1 — S1 byte-faithful + discriminating**: 4 RoomType lifecycles match the ADR-012 amendment exactly (states + `rule_matched` + dispatch); per-state wrong-event negatives + full-chain per type; pure code, backward-compat (`setup`/`closed` preserved).
- **G2 — S2 c1 structurally enforced**: AST guard (`override.py` no `.call`) + spy `call`==0 across all 7 override combos (discriminating); composes with Layer-3 (effective_chain still runs every per-candidate filter); empty-chain fail-loud; no new routing `LLMPurpose`.
- **G3 — S3 c2 fully faithful**: opt-in + fail-closed allowlist (`ConfigError`); the Y2-α `_build_child_env` strips parent `ANTHROPIC_BASE_URL`, wired into **both** subprocess paths; the exact AC#2b parent-inheritance discriminating test + anti-leak-when-allowlisted + message-content tests; `api_key_env` indirection.
- **G4 — S4 faithful**: bootstrap composes existing loaders in order; `StartupError`; `render_startup_error` covers `.violations` + `.decision_trace` + S2/S3 hints; message-content asserted (§4) + `ConfigError`→`StartupError` boundary (§5).
- **G5 — batched + RC-23**: 7 commits per the atomic graph (prelude resolves shared seams, S4 last); amendments RC-23-safe (`— Implemented`, no `Status:`-value literal); ADR-023 Accepted by the architect.
- **G6 — gates green independently**: 149 P2.7-scope tests pass; ruff clean; mypy --strict clean on the new source (override/bootstrap/claude_code_cli/state_machine/router). Source≠sink coverage per sub-item (S1 full-chain, S2 override→selection, S3 env round-trip, S4 config-dir→LLMLayer) — distributed across the per-item test files (no single integration file; acceptable — each is end-to-end).

Minor notes (non-findings, for awareness): (a) `apply_global_override`'s signature is `-> tuple[list, dict]` (enriched beyond ADR-023 D2's pinned `-> list[ModelId]`) — a *sound* enrichment to carry `drop_reasons` for the trace, not a defect. (b) The c1 spy test's docstring says it runs "through `select_model_and_provider`" but the loop calls `apply_global_override` directly — the AST guard + direct spy still cover the new override surface (where the c1 risk lives); cosmetic docstring nit. (c) integration-fix `0531c93` (dedup `GlobalLLMOverride`) is an RC-17 fixup, benign (no product-logic).

## Net

Three sub-items (S1/S3/S4) match the plan + Accepted ADR-023 + the amendments on every atomic, with discriminating tests for the load-bearing invariants (the S2 c1 spy/AST guards, the S3 env-inheritance fail-closed, the S1 per-arc transitions, the S4 message content). S2's constitutional core (routing-is-code) and Layer-3 composition are solid. The single 🟡 is a real but narrow deviation: the **default keep-mode** unknown-cost **trace visibility** mandated by Accepted ADR-023 D2 + plan AC#3b is not implemented, and the keep-mode test is non-discriminating — so I do **not** wave it through. **Verdict: needs_architect** — route Y1 (α fix the keep-mode trace + discriminating test, or β amend D2). Per ADR-008 Route B, state auto-advances; with one 🟡 carried, the architect routes before R0-A/R0-B close. I did not accept anything or advance state.
