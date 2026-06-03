---
task_id: P3.5
review: R0-A
stage: impl
reviewer: architect-partner
lens: >-
  R0-A (in-family, impl-stage) on the 8-atomic impl @ 7bec33d, against the
  REVISED ADR-029 (post plan-stage routing-absorption). The dual-lens R0-B
  re-probes the same surface in parallel. I traced code paths, not the impl's
  self-report (the P2.1/P2.2 fabricated-probe discipline; dual-lens-r0b.md §RC-20).
date: 2026-06-03
impl_commit: 7bec33d
artifacts_reviewed:
  - src/orchestrator/plugins/schema.py
  - src/orchestrator/plugins/loader.py
  - src/orchestrator/plugins/code.py
  - src/orchestrator/api/app.py (_build_context wiring)
  - tests/plugins/ (constitution, loader, merge, failure_modes)
  - plugins/demo/ + config/tools.yaml (host-side word_count classification)
verdict: needs_architect
findings:
  blocking: 0
  needs_architect: 2
  clean_notes: 3
gates_verified:
  ruff: pass
  mypy: pass (96 src files)
  pytest_plugins: pass (31)
  pytest_api_integration: pass (137)
note: >-
  The implementation is CORRECT and faithfully delivers the revised ADR-029 — the
  constitutional spine holds structurally (gate/executor/MCP decision-logic diff
  is EMPTY, verified main..impl), the R0-A-Y1 shadow-bypass is CLOSED (collision
  check covers tool_impls vs host local_tools), the R0-B-R1 collision-before-import
  ordering is correct in code, the R0-B-Y4 atomic discard is correct, and Posture
  A's L1/L1b/L2 are fully inscribed in code.py (no fake isolation). Gates verified
  green independently (not trusting the landing commit). Both Y findings are
  TEST/DEMO quality, NOT runtime defects (lean α). Y1 — the regression guards for
  the security-load-bearing admit-code paths are weak: the R1-ordering test is
  vacuous (the import-time raise is caught by code.py either way, so it passes
  regardless of ordering), and the D4 code-load fail-closed + Y4 atomicity tests
  short-circuit at collision-check BEFORE reaching the path they claim to test.
  Y2 — the demo's tools.yaml is dead (word_count not in contributions.tools →
  filtered out), so the demo live-exercises only 4 of 5 surfaces + ships a
  misleading file.
verdict_history:
  - at: impl-stage
    verdict: needs_architect
    by: architect-partner
    note: Y1 weak regression guards on admit-code security paths + Y2 demo dead tools.yaml (both α, both test/demo quality not runtime)
---

# R0-A (impl-stage) — P3.5 (Plugin system impl @ 7bec33d)

## 0. Method + gates

I traced the code, not the impl's self-report. Gates verified independently
(my standing discipline — a landing "gate green" is not taken on faith):

- `ruff check src/orchestrator/plugins tests/plugins` → **pass**.
- `mypy src/orchestrator` → **pass** (96 source files, no issues).
- `pytest tests/plugins` → **31 pass**; `pytest tests/api tests/integration` →
  **137 pass** (the `_build_context` blast radius is clean).

So nothing is broken at runtime. The 2 Y findings are about **test/demo quality**,
not correctness — the implementation itself is sound (§2).

## 1. Verdict — `needs_architect` (2 Y; 0 🔴)

| # | Sev | Finding | Lean |
|---|---|---|---|
| **Y1** | 🟡 | Regression guards for the **security-load-bearing admit-code paths are weak**: the R1 collision-before-import test is **vacuous**; the D4 code-load fail-closed + Y4 atomicity tests **short-circuit at collision-check** before reaching the code path they claim to test. The *code* is correct; the *tests* don't guard it. | **α** (fix the tests — they guard the blocking-R1 + non-negotiable HR#5 invariants) |
| **Y2** | 🟡 | The demo's `plugins/demo/tools.yaml` is **dead** (`word_count` is in `tool_impls`, not `contributions.tools`, so the loader filters it out). The demo live-exercises only **4 of 5** surfaces (the standalone tool-classification surface is tested elsewhere, not in the demo) and ships a misleading file. | **α** (declare a classification-only tool in `contributions.tools`, or drop the dead `tools.yaml` + adjust the "five surfaces" claim) |

Both are α-cheap; neither blocks runtime. The spine + the security crux are
correctly implemented (§2).

## 2. What's correct — the 7 review points, traced (spine + code-trust HELD)

**(1) Execution downstream-of-gate + empty decision-diff — ✓ CLEAN.**
`git diff origin/main..7bec33d` on `autonomy/scoring.py`, `autonomy/emission.py`,
`agents/tool_dispatch.py`, `tools/executor.py`, `mcp/` is **empty** — the gate, the
executor, and the MCP client are genuinely untouched (the ADR-027 D2 / ADR-028 D6
empty-diff invariant, extended to the executor, HOLDS). The `_build_context` wiring
(`api/app.py:158+`) adds **one** aggregation pass after the four loaders and merges
`plugin_result` into the registries; a plugin tool's `ToolMeta` enters the same
`tools` dict that flows `process_tool_calls → emit_gate_decision`. No second
decision surface.

**(2) Plant-bypass — ✓ CLEAN; the R0-A-Y1 shadow-fix landed correctly.**
`loader.py::_collision_check:239-256` checks `tool_impls` names against **(i)**
`host_local_tool_names` (closes the shadow-bypass — a plugin can't shadow the
sandboxed `read_file`) and **(ii)** cross-plugin `tool_impls`. The shadow test
(`test_failure_modes.py:403`) is **non-vacuous**: without the check, `read_file`
would land in `result.local_tools`; the assertion `"read_file" not in
result.local_tools` is sensitive to the check's presence. The deliberate NON-check
of `tool_impls` vs `host_tools` (loader.py:233-238) is **correct by design**: a
plugin's own `contributions.tools` ARE checked against `host_tools` (line 222, so a
plugin can't re-classify a host tool), while a plugin may *provide an impl* for a
host-**pre-classified** name (the D7/R0-B-Y2 mechanism) — the host's classification
stays authoritative, so this is gate-tiered, not a bypass. G2's "novel-name
LocalToolFn → `UnknownToolError` → refused" still holds (gate unchanged).

**(3) D2 ordering (R0-B R1) — ✓ CODE CLEAN.** `_load_plugin` runs `_collision_check`
(loader.py:339) and returns `None` on collision (`:352`) **before** the code-load
(`:415`). A refused plugin's `importlib` (and its import-time code) never runs. The
collision-check operates on **manifest names** (no import needed). *(The test that
should guard this is vacuous — Y1.)*

**(4) Atomic merge (R0-B Y4) — ✓ CODE CLEAN.** `_load_plugin` returns a per-plugin
`PluginLoadResult | None`; on ANY failure it returns `None` (collision/load/code).
`load_plugins:503` skips `None`; `seen_*` + `merged` update only after full success
(`:507-518`). The host registries are merged from `plugin_result` (which excludes
refused plugins) at `_build_context`. A half-loaded plugin leaves zero trace.
*(The test that should guard this short-circuits — Y1.)*

**(5) Posture A L1/L1b/L2 — ✓ CLEAN; fully inscribed, no fake isolation.**
`code.py:7-19` docstring inscribes L1 (no technical isolation + zero env protection
— in-process reads all `os.environ`), L1b (import-time ungated by construction), L2
(VOIDS the ADR-028 D5 per-turn liveness bound, server-wide DoS) — verbatim with the
revised ADR-029 D4. The import is `spec_from_file_location` + `exec_module`
(`:49-53`), honestly noted as running top-level code (L1b). No `RestrictedPython` /
audit-hook pretense (Posture C correctly absent). The architect Accepts the real
surface.

**(6) No new `LLMPurpose` + load-is-code + constitution test — ✓ CLEAN.**
`tests/plugins/test_constitution.py` is **non-vacuous**: p1 AST-walks `plugins/`
forbidding `decide_tier`/`emit_gate_decision`/`score`/`select_model_and_provider`
+ `gate` as a Name; p2 forbids `llm.providers` imports; p3 asserts the frozen
9-value `LLMPurpose` set is unchanged; p4 forbids `select_model_and_provider` **and**
asserts it DOES exist in `llm/router.py` (a real non-vacuous guard). Loading is
discovery+validate+register — code, not judgment.

**(7) Fail-closed loading — ✓ CODE CLEAN.** Every failure path refuses-and-continues
(per-plugin isolation): YAML parse / not-a-mapping / `ValidationError` / id-mismatch
/ unmet `min_host_contract`/`model_ids`/`room_types` (loader.py:109-167); collision
→ `None`; loader errors → `None`; code-load → `None` (`:420`). The colon-split in
`code.py:76` is safe — `schema.py:34-41` validates every `tool_impls` ref is
`<module>:<callable>` at manifest-validation time, so a malformed ref fails closed at
step 2 (never reaches `code.py`). *(The code-load fail-closed paths' dedicated tests
are weak — Y1.)*

## 3. Y1 🟡 — weak regression guards on the security-load-bearing admit-code paths

The *code* is correct (§2.3/2.4/2.7). But four tests meant to guard the
**highest-stakes paths** (the R1 blocking-fix ordering; the D4 admit-code fail-closed;
the HR#5/Y4 atomicity) do **not** exercise what they claim — a future refactor could
regress these invariants with the suite still green.

- **(a) `test_collision_refused_plugin_not_imported` (`:451`) — VACUOUS.** The
  module does `raise RuntimeError(...)` at import; the test asserts no exception +
  `local_tools == {}`, on the premise "if imported before the collision check, the
  error would propagate." **It would not.** `code.py:87` `except Exception → raise
  PluginCodeLoadError`, caught at `loader.py:420 → return None`. So **both** orderings
  (collision-first, or the R1-bug import-first) yield `local_tools == {}` and no
  propagation — the test passes regardless of ordering. **Fix:** the module writes an
  observable import-time **sentinel** (e.g. a file) *without raising*; assert the
  sentinel does **not** exist (proving `exec_module` never ran).
- **(b) `test_broken_module_import_refused` (`:500`) — short-circuits.** It declares
  `contributions.tools: ['my_tool']` with `host_tools={"my_tool": …}` → collision at
  `loader.py:222` (step 3) → refused **before** the code-load. The broken-import path
  in `code.py` is never reached. **Fix:** put `my_tool` only in `tool_impls` (the
  pre-classify path) so collision-check passes and the broken import is actually hit.
- **(c) `test_missing_callable_in_module_refused` (`:541`) — same short-circuit**
  (`my_tool` in both `contributions.tools` and `host_tools` → collision-refused
  before the `getattr`-None path). Same fix.
- **(d) `test_partial_plugin_leaves_no_trace` (`:111`, the Y4 atomicity guard) —
  short-circuits.** It declares `tools: ['bad_tool']` with `host_tools={"bad_tool":
  …}` → collision at step 3, **before** the role (`bad_role`) is loaded into the
  per-plugin intermediate. So the genuine half-register scenario (non-code surfaces
  load → code-load fails → intermediate discarded) is **never exercised** — `bad_role`
  is refused before it is ever loaded. **Fix:** make `bad_tool` a `tool_impls`-only
  pre-classified tool (no `host_tools`/`contributions.tools` collision) with a broken
  impl module, so the role loads into the intermediate and the test proves the
  intermediate is discarded on code-failure.

**Why it matters:** R1 was the cross-family **blocking** finding; HR#5/Y4 atomicity
is non-negotiable. Their regression guards being vacuous/short-circuiting means the
project's largest security surface has no real test catching a reordering or a
half-register regression. Lean **α — fix the four tests** (cheap; restores the guard).
The happy-path code-load IS covered (`test_loader.py:235/278`), so `code.py` isn't
untested — only its failure/ordering/atomicity guards are weak.

## 4. Y2 🟡 — the demo's `tools.yaml` is dead; demo live-exercises 4 of 5 surfaces

`plugins/demo/plugin.yaml` declares `tool_impls: {word_count: …}` and leaves
`contributions.tools` empty (commented out). But `loader.py:374,383` filters the
plugin's `tools.yaml` by `declared_tools = set(contributions.tools)` (= ∅), so
`plugins/demo/tools.yaml` (which classifies `word_count: rev 10`) is **loaded then
discarded** — a dead file. Consequences: **(a)** the demo does **not** live-exercise
the standalone tool-classification surface (`contributions.tools` is empty; that
surface is covered separately by `test_loader.py:228`), so the D7 "all five surfaces"
claim is true of the test suite but not of the demo bundle; **(b)** the dead
`tools.yaml` **misleads** — a reader learning the mechanism sees `word_count: rev 10`
in the plugin and may think *that* enables AUTO_EXECUTE, when in fact it is ignored
and the **host** `config/tools.yaml` entry (rev 10, added for the demo) is what tiers
it. Lean **α** — either give the demo a real classification-only tool in
`contributions.tools` (it will cap to rev 0 = HARD_CONFIRM per D5 — itself a useful
demonstration), or remove the dead `tools.yaml` and state the demo exercises the
tool-classification surface via the host-pre-classify + `tool_impls` path.

## 5. Clean notes (no action; recorded)

- **N1 (commend) — the reversibility cap is correctly one-directional.**
  `_apply_reversibility_cap:298-303`: a plugin's own tool (no host entry) → `rev 0`;
  a host-classified tool → `min(plugin, host)`. So a plugin can **never** self-grant
  AUTO_EXECUTE — only the host (operator) classification raises the tier. This is the
  right security property and `test_loader.py:313` guards it.
- **N2 — `config/tools.yaml` now permanently classifies `word_count` (rev 10)** for
  the demo. Minor leak: with the demo plugin absent, `word_count` is
  classified-but-not-implemented → `TOOL_FAILED(not_implemented)` if ever called.
  Harmless (a spare classification), and prescribed by D7; noted for the audit trail.
- **N3 — the `tool_impls` module ref is not directory-scoped.** `code.py:77`
  `plugin_dir / f"{module_name}.py"` — a `module_name` with `../` would resolve
  outside the plugin dir. **Moot under Posture A** (a curated plugin already runs
  arbitrary in-process code per L1), so not a new capability; noted only so a future
  Posture-B (untrusted-provenance) slice scopes the ref to the plugin dir.

## 6. Routing asks (architect)

1. **Y1** — α: require the four test fixes before merge? (lean yes — they guard the
   blocking-R1 ordering + the non-negotiable HR#5 atomicity; the code is correct but
   unguarded against regression).
2. **Y2** — α: demo exercises the tool-classification surface for real (or drop the
   dead file)? (lean yes; cheap).

Both are α-cheap and the impl is otherwise clean + gate-green. The **dual-lens R0-B**
re-probes this surface in parallel; I expect it to converge on Y1 (it is precisely the
runtime/regression-guard lens). No 🔴; the spine + the admit-code security crux are
correctly implemented in the code.
