---
task_id: P3.7-remote
stage: architect-routing-on-impl
adr_under_review:
  - ADR-031
  - ADR-032
impl_branch: claude/P3.7-remote-impl
routed_by: architect (Peidong)
routed_via: orchestrator
date: 2026-06-04
reviews_routed:
  - docs/process/reviews/P3.7-remote/R0-A.md             # blocking: B1 gate-red + Y1 needs_architect + 1 advisory
  - docs/process/reviews/P3.7-remote/plan-vs-impl.md     # needs_architect: PvI-1 + PvI-2 + 1 advisory
  - docs/process/reviews/P3.7-remote/R0-B-cross-family.md # impl-stage needs_architect: I1 (1🟡) + 7🟢
fix_commits:
  - 0563034   # fix1 — Y1: restore dual posture (operator-placed→A, fetched→B)
  - fc13ba0   # fix2 — B1: remove 2 unused type:ignore (mypy gate-red)
  - 8353d85   # fix3 — I1: document import-boundary + anti-laundering + api_key_env guarantees
disposition: Y1→restore-per-contract; B1→α; I1→α
---

# Architect routing — P3.7-remote impl-stage (3 impl reviews + 3 junior fixes)

Architect (Peidong) routed the three impl-stage reviews on 2026-06-04 via the orchestrator. **3-way convergence** (R0-A in-family `blocking`, R0-B cross-family `needs_architect`, senior plan-vs-impl `needs_architect`) on the same two issues — a gate-red and the ADR-031 D3 ↔ code Posture-A divergence. The junior pushed three fixes; the senior re-verified the canonical gate + the contract restoration + the I1 absorption.

## Y1 / I1 / PvI-1 (converged: ADR-031 D3 ↔ code) → **restore-per-contract** (fix1 `0563034`)

All three reviewers flagged that the impl had retired Posture A entirely (B-for-all) — safer than the contract, but diverging from the **freshly-Accepted ADR-031 D3** (operator-placed → in-process Posture A; the in-process `importlib` path physically exists). R0-A/R0-B leaned α-amend-the-ADR; the senior plan-vs-impl additionally diagnosed an **ADR-031 internal contradiction** (D3 "A preserved / path exists" vs Consequences "A is gone") that I authored when absorbing the plan-stage R2 routing.

**Architect ruling: RESTORE the dual posture per the Accepted contract** (make the *code* match the ADR, not amend the freshly-Accepted ADR). The junior's **fix1 (`0563034`)**:
- `plugins/code.py` — split into **`_load_posture_a_fns`** (in-process `importlib`/`exec_module`, operator-placed — ADR-029 D4 curation=trust) and **`_load_posture_b_fns`** (`_PostureBFn` subprocess closures, fetched-only); `load_plugin_code(..., *, provenance)` branches: `fetched → Posture B`, `operator_placed → Posture A`.
- `plugins/loader.py` — threads `provenance=candidate.provenance` (origin-set: `operator_placed` from `plugins_dir`, `fetched` from `fetched_plugins_dir`) into `load_plugin_code`.
- Tests — `test_provenance.py` `pv5` (fetched → `_is_posture_b_subprocess`=True; operator-placed → no marker, in-process A) + `pv8` (operator-placed no subprocess env); `test_failure_modes.py` updated (Posture-A broken-import → **refused-at-load**, not load-then-call-fail); `test_p3_7_remote_plugins.py` demos updated.

**Senior re-verification (this routing):** ✅ dual posture restored correctly — operator-placed runs in-process Posture A; fetched runs Posture B subprocess; **fetched is test-enforced-unreachable for Posture A** (the `provenance=="fetched"` branch only ever calls `_load_posture_b_fns`; `pv5` asserts the `_PostureBFn` marker on fetched, structurally proving in-process A was not used). The ADR-031 D3 contract now matches the code — **no ADR amendment needed** (the architect's restore-route resolves the D3↔code divergence *and* the D3↔Consequences contradiction is moot: the in-process path exists exactly as D3 says).

## B1 / PvI-2 (gate-red) → **α** (fix2 `fc13ba0`)

Canonical `mypy --strict` (files=src,tests) was RED — 2 unused `type: ignore` in `tests/plugins/test_posture_b.py:153,172`. **fix2 (`fc13ba0`)** deleted the two comments.

**Senior re-verification:** ✅ `uv run mypy --strict` → **"Success: no issues found in 235 source files."**

## I1 structural guarantees → **α absorb** (fix3 `8353d85`)

The architect routed the three I1 structural guarantees R0-B confirmed (G5/G6/G7) to be made **explicit in code** (not just behaviourally true). **fix3 (`8353d85`)**:
- `_harness.py` — docstring clarified: **fetched-plugins-only**; operator-placed run in-process via `importlib` (Posture A) and **never spawn this harness** (import boundary = the isolation contract).
- `provenance.py` — docstrings reference the two `code.py` loaders; state **fetched code NEVER runs in-process** and **`api_key_env` is structurally unreachable** for the fetched subprocess (`_PostureBFn` builds `MCPServerConfig` without `api_key_env`, so `build_scoped_env` never injects a secret); the disjoint-root anti-laundering guard is referenced.
- `plugins/demo_posture_b/tools_impl.py` — misleading "host never imports this" comment fixed.

**Senior re-verification:** ✅ all three guarantees are both **true in code** (verified) and now **documented**: (a) **import boundary** — operator-placed→`_load_posture_a_fns` in-process / fetched→harness child; (b) **api_key_env/env boundary** — `MCPServerConfig` for the harness is built with no `api_key_env`; the env-leak probe (`env_probe_tool` / `test_posture_b.py`) confirms orchestrator secrets are absent in the child; (c) **anti-laundering** — `loader.py` disjoint-root guard (both directions) + provenance-by-origin.

## Senior re-verification — canonical gate (independent, per dispatch)

| Gate | Result |
|---|---|
| `ruff check .` | 🟢 pass ("All checks passed!") |
| `ruff format --check .` | 🟢 pass ("238 files already formatted") |
| `mypy --strict` (canonical files=src,tests; **not** `mypy --strict .`) | 🟢 **pass** ("Success: no issues found in 235 source files") |
| `pytest` | 🟢 pass (full suite green) |

**All four canonical gates GREEN.**

## Verdict bumps (RC-10)

The three impl-stage reviews are bumped → `clean` (verdict_history appended):
- `R0-A.md`: `blocking` → `clean` (B1 fixed `fc13ba0`; Y1 restored `0563034`; advisory noted).
- `plan-vs-impl.md`: `needs_architect` → `clean` (PvI-2 fixed `fc13ba0`; PvI-1 resolved by restore-per-contract `0563034` — note: architect chose restore over the senior's α-amend recommendation, which is the architect's routing call; PvI-3 advisory unchanged, P4).
- `R0-B-cross-family.md`: impl-stage `needs_architect` → `clean` (I1 absorbed `8353d85`; the impl entry is on disk, so it is bumped per dispatch).

ADR-031 + ADR-032 remain **Accepted** unchanged (the restore-route means no ADR edit — the code conforms to the contract).

## State / next

`.workflow/P3.7-remote.yaml` stays architect-managed (this split cycle). The impl branch carries the 9 atomics + 3 fixes + the 3 bumped reviews + this routing record. **All canonical gates green; all impl-stage findings resolved.** Next: architect walks the **final merge** of `claude/P3.7-remote-impl` (the orchestrator will request architect go-ahead before merging, per never-merge-without-architect).
