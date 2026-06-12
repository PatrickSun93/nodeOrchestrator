---
task_id: P6.2
kind: R0-A
stage: impl
surface: product
slice_type: bug-fix (dual-lens; requires_cross_family_review=true)
reviewer: architect-partner
verdict: needs_architect          # one trivial P6.2-introduced gate miss (Y1) + a pre-existing project-hygiene observation (O1) to route; C1/D1 logic is correct + fail-on-revert-verified
branch_reviewed: origin/claude/P6.2-impl
commit_reviewed: 5838ce3
reviewed_against:
  - docs/process/senior-plans/P6.2.md (D-mech-A)
  - docs/process/architect-briefs/P6.2.md (Architect ratification — 2026-06-11)
gates:
  ruff_check: pass
  ruff_format: FAIL (Y1 — C1 test file; + 51 pre-existing untouched files, O1)
  mypy_strict: pass (310 source files)
  pytest: pass (full suite, exit 0)
  fail_on_revert: verified (C1 + D1, empirically reverted → FAIL)
  spine: unchanged (diff = 6 files; gate / _execute_local_call / run_pipeline / COUNTDOWN untouched)
  new_llmpurpose: none (purposes.py not in diff)
---

# P6.2 — impl-stage R0-A (dual-lens, architect-partner)

Two ratified atoms, two commits, no ADR (`plan_has_adr=false`). Reviewed `origin/main...origin/claude/P6.2-impl` @ `5838ce3` against the senior plan (D-mech-A) and the brief's 2026-06-11 ratification. Gates run in an isolated detached worktree at `5838ce3` (`uv sync --all-extras`; shared tree stayed on `main`, no checkout).

**Bottom line:** C1 and D1 are **correct, in-scope, and empirically fail-on-revert**. `ruff check`, `mypy --strict` (310 files), and the **full pytest suite are green**. The audit invariant, no-double-actuation property, router purity, and `select_model_and_provider` back-compat all hold and are verified below. The **only** P6.2-introduced blemish is a trivial **`ruff format` miss in the C1 test file (Y1)** — format-only, test-only, one-command fix. Separately, `main` is already `ruff format`-dirty under the lockfile-pinned ruff (O1, pre-existing, not P6.2). Both go to you to route.

---

## 1. C1 — empty/blank tool-arg string → `{}`

`openai_compatible.py` `_parse_chat_completion` (diff):

```python
if isinstance(args_raw, str):
    arguments = json.loads(args_raw) if args_raw.strip() else {}
else:
    arguments = args_raw or {}
```

Conforms exactly to ratified **C-lean** + the scope boundary:

- **AC1** `strip()` guard; `""` and `"   "` → `{}` (whitespace-only `.strip()` is falsy → `else {}`). ✓
- **AC2** genuine malformed `"{bad"` is a non-blank str → `json.loads` runs → `JSONDecodeError` → `PermanentProviderError` at `:283`, **untouched**. ✓
- **AC3** missing `arguments` key → `tc["function"]["arguments"]` `KeyError` → still `PermanentProviderError`; the fix did **not** widen (None/absent ≠ empty-string). ✓
- **AC4** Tests `tests/llm/test_openai_compatible_provider.py::TestToolCallArgumentsNormalization` (+3): `""`→`{}`, `"   "`→`{}`, `"{bad"`→`PermanentProviderError`. ✓

**Fail-on-revert — empirically confirmed.** Reverted the guard to `main`'s line, ran the class: `test_empty_string…` and `test_blank_string…` **FAIL** (`PermanentProviderError: malformed tool_call: Expecting value: line 1 column 4`), `test_malformed…` still passes. Restored; tree clean.

C1 is clean.

---

## 2. D1 — call-time transient fallback (the cross-family-load-bearing atom)

`select_viable_routes` (new in `router.py`) + the adapter loop in `RealLLMRouter._async_call`. D-mech-A as ratified. Each acceptance criterion:

- **AC1 router purity** — `select_viable_routes` makes **zero `provider.call()`** (only `provider.health_check()`); the `.call()` loop lives in the adapter. `router.py:15` ("zero LLM calls") holds; `tests/llm/test_constitution.py::test_constitution_override_path_makes_no_llm_call` (which drives the **untouched** `select_model_and_provider` directly, line 267) and the `select_model_and_provider`-absent structural tests across `tests/{mcp,plugins,tools,reentry}/test_constitution.py` all pass (full suite green). ✓
- **AC2 back-compat** — `select_model_and_provider` is **byte-identical** (the diff only *adds* `select_viable_routes` after line 287). Its per-candidate filter block — override drop/kept-unknown-cost trace, registry → capability → provider → tools → health_check, identical reason strings — is reproduced in `select_viable_routes` verbatim; the sole difference is `append+continue` vs `return`. So `viable[0]` is provably the same `RouteResult` `select_model_and_provider` would return, with the same `decision_trace` prefix. The ~30 `test_router.py` callers + `test_e2e_fallback.py` pass untouched. ✓ (Junior chose the **standalone** factoring the plan explicitly permitted — see N2.)
- **AC3 loop semantics** — `TransientProviderError` → append call-trace entry, continue; `PermanentProviderError` → **not caught**, propagates (no fallback, D4 permanent semantics); success → return that `LLMResponse`. Each route called with `model_id_requested=route.model_id_requested`. ✓
- **AC4 all-transient exhaustion** — terminal `NoSuitableModelError("all viable providers raised TransientProviderError", decision_trace=call_trace)`, one `dataclasses.asdict(RouteCandidate(...))` entry per attempted route (`{model_id, provider_id, accepted: False, reason: "call-time transient: …"}`) — ratified option **(b)**, not a re-raised transient. Note `select_viable_routes` never returns `[]` (it raises its own `NoSuitableModelError` on an empty viable set), so the adapter's terminal raise is reached **only** when ≥1 route was tried and all were transient — the message is accurate by construction (no "all transient" lie on a zero-viable chain). ✓
- **AC5 audit invariant** — every `RouteResult.model_id_requested` is the chain head (`agent_config.default_model`); a fallback answer yields `requested != used`. Empirically: `test_transient_primary_falls_to_fallback` asserts `model_id_requested == PRIMARY_ID`, `model_id_used == FALLBACK_ID`, `requested != used` — **passes** in the green suite. This is the exact contract the agy-cli review hardened, now reachable on the call-time path. ✓
- **AC6 fail-on-revert** — `tests/api/test_llm_adapter.py` (+3) exercises `_async_call` end-to-end with an `_ErrorOnCallProvider` double (health-passes, raises a chosen `ProviderError` on `.call()`; no provider-error behavior added to production code) + `MockProvider` for the success leg. **Empirically confirmed:** reverted the adapter to `main`'s single-call shape → `test_transient_primary_falls_to_fallback` **FAILS** (`TransientProviderError: rate limited` propagates at the call site instead of the fallback answering) and `test_all_transient…` **FAILS**; `test_permanent…` correctly still passes (permanent-propagation is loop-independent). Restored; tree clean. ✓
- **AC7 ADR note** — see §3. ✓

**No double-actuation** — the loop returns on the **first** successful `.call()`, so at most one `LLMResponse` is ever produced; a `TransientProviderError` leg produced **no** response → nothing to actuate, and tool execution is downstream of the response (never inside `call()`; ADR-003 — CLI providers `can_use_orchestrator_tools()=False`). The brief's spine argument holds as implemented. ✓

D1 is clean.

---

## 3. ADR-002 D4 "Implemented" note — accurate

`### 2026-06-12 (P6.2 / D1) — Implemented (call-time transient fallback)` under `## Amendments`, matching the weight/shape of the existing `2026-06-11 (agy-cli-provider)` and `2026-06-02 (P2.7 / ADR-023)` notes. Records (i) the call-time half is now implemented via D-mech-A (`select_viable_routes` health-checks once up-front, adapter iterates, router purity preserved) and (ii) safety = side-effect-free content-gen → no double-actuation (ADR-003). Every clause matches the code as shipped. One-line clarification on an already-Accepted decision → **no Accept gate** (`plan_has_adr=false`), correct. Date is the impl commit's UTC date. ✓

---

## 4. Spine / LLMPurpose

Diff = **6 files** (`ADR-002`, `llm_adapter.py`, `openai_compatible.py`, `router.py`, `test_llm_adapter.py`, `test_openai_compatible_provider.py`). The constitutional spine (`_execute_local_call`, the autonomy gate, `run_pipeline`, COUNTDOWN) is **not in the diff** — zero-diff by inspection. `purposes.py` is **not in the diff** → **no new `LLMPurpose`**; the adapter's chain-walk is the mechanical execution of D4's inscribed ordering, not a judgment surface. ✓

---

## 5. Findings to route

### 🟡 Y1 — `ruff format` miss in the C1 test file (P6.2-introduced, format-only, trivial)

Under the **uv.lock-pinned `ruff 0.15.12`** (the version `uv sync` installs — canonical for the project's own tooling), `tests/llm/test_openai_compatible_provider.py` **would be reformatted**: the three `_make_provider(lambda r: httpx.Response(200, json=_tool_call_response("…")))` lines in the junior's added `TestToolCallArgumentsNormalization` collapse from 3-line to single (<100-char) lines. **`origin/main`'s version of this file is `already formatted` (clean) under 0.15.12** → the junior's added code introduced the drift. `contributing.md:195` mandates `ruff format` pass. The other 4 touched files are format-clean.

- Cost to fix: one command (`ruff format tests/llm/test_openai_compatible_provider.py`) + recommit on the impl branch. Zero behavior change.
- **My lean: α (fix-now)** — keep the slice net-neutral on format cleanliness; don't add new drift on top of O1. But it interacts with O1 (below), so it's yours to route.

### 📋 O1 — `main` is `ruff format`-dirty under the locked ruff (pre-existing, NOT P6.2)

`ruff format --check` flags **52 files**; **51 are P6.2-untouched** (`api/app.py`, `auth/*`, `pipeline/*`, `plugins/*`, `sandbox/*`, `tools/*`, …). Those landed across P4/P5 and predate this slice → `main` itself currently fails the `ruff format` half of the gate under the lockfile-pinned `ruff 0.15.12`. The manual gate discipline has silently drifted (most likely a `uv.lock` ruff bump without a repo-wide reformat — cf. the #95 prettier follow-on in the same spirit). **Not P6.2's to fix.** Surfacing as a candidate **format-hygiene follow-on** (one `ruff format .` + commit, its own dev-harness-light slice). You may prefer to fold Y1 into it (β) rather than have the junior touch the impl branch for 3 lines.

### NITs (non-blocking, FYI — no action expected)

- **N1** `llm_adapter.py` module + class docstrings (lines 4, 8, 39) still name `select_model_and_provider`; the code now calls `select_viable_routes`. The semantic claim ("decision-free; routing decided by the router, not the adapter") still holds — only the function name is stale. Doc-drift.
- **N2** `select_model_and_provider` is now **production-dead** (only test callers remain); its ~80-line filter block is duplicated in `select_viable_routes`. This is the **plan-blessed standalone factoring** (D1.2: "Either factoring is acceptable; the constraint is the unchanged observable contract, not the internal shape") — it bought byte-identical safety for the 30+ callers. FYI only; an optional future delegation cleanup, **not** in-scope to demand now (architect-deferral literal-reading).
- **N3** `select_viable_routes` builds each `RouteResult.decision_trace` cumulatively, so a 2nd viable route's trace contains the 1st route's `matched` entry. Harmless — the adapter never reads `route.decision_trace` (dead data, same as pre-existing on the `select_model_and_provider` path). FYI.

---

## 6. Verdict

**`needs_architect`.** C1 + D1 are logically correct, in ratified scope, fail-on-revert-verified, mypy/ruff-check/pytest-green, spine-clean, no new `LLMPurpose`, ADR note accurate. The slice is substantively merge-ready. Two routing calls are yours:

- **Y1** (trivial P6.2-introduced `ruff format` miss in the C1 test file): **α fix-now** (junior re-formats + recommits) vs **β fold into the O1 follow-on**. My lean: α.
- **O1** (pre-existing 51-file `main` format drift under locked ruff): dispatch a dedicated format-hygiene follow-on, or accept-as-known. My lean: separate follow-on.

I surface; I do not route. No `routing.md` written until you call.
