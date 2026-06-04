---
task_id: P3.7-content
kind: architect-routing-on-impl
date: 2026-06-04
stage: impl
impl_commit: b84d451
doc_fix_commit: 13f037f
reviews_acked:
  - plan-vs-impl.md   # senior — 11/11 atomics faithful; 1 finding (PvI-1); canonical gate + 1653 tests green
routed_via: orchestrator   # split-cycle: architect owns state; ruling relayed through the orchestrator session
decisions:
  PvI-1: >-
    canonical-is-gate — the pyproject `[tool.mypy] files=["src","tests"]` scope is authoritative
    (option A); plugins/ is deliberately outside the typed surface (Posture-A bundles are
    path-loaded at runtime and may carry same-named `tools_impl.py`). NO impl/content change.
    Fix the documentation: contributing.md §205 dropped the whole-tree `.` form and now states
    the plugins/ scope exclusion (commit 13f037f).
---

# P3.7-content architect routing — impl stage (PvI-1 → canonical-is-gate + doc-fix)

**Architect decision (2026-06-04, architect = Peidong, relayed via the orchestrator session):**
the senior plan-vs-impl review carried a single open finding, **PvI-1** (the `mypy --strict .`
whole-tree form is RED on a duplicate top-level module `tools_impl`, while the canonical
pyproject-scoped `mypy --strict` is GREEN). Architect rules **option A — canonical-is-gate**:
the `pyproject.toml [tool.mypy] files=["src","tests"]` scope is the authoritative gate, and
`plugins/` is intentionally outside the typed surface. **No impl or content change** — the
shipped P3.7-content code is correct and green under the real gate. The only action is a
**documentation fix** to `contributing.md` §205, landed by junior at **13f037f**.

This file is the **signal artifact for the senior revision session** (impl stage). Senior
re-verifies the doc fix + canonical gate, then bumps the plan-vs-impl verdict to `clean`
(R0-A is already clean). No code revision commit is routed.

## Issue map (1 finding → 1 route)

| Issue | Raised by | Route |
|---|---|---|
| **PvI-1** — `mypy --strict .` (whole-tree form) duplicate-module collision (`plugins/demo` vs new `plugins/context` `tools_impl.py`) | senior plan-vs-impl | **canonical-is-gate + doc-fix** (option A) |

## Per-issue routing

### PvI-1 → canonical-is-gate + doc-fix (option A)

- **Ruling**: pyproject `[tool.mypy] files=["src","tests"]` is the authoritative mypy gate.
  `plugins/` is excluded by design — Posture-A bundles are operator-placed, loaded by path at
  runtime, and may legitimately carry same-named `tools_impl.py` files (the flat-module
  collision only surfaces under the whole-tree `.` argument, which is not the gate).
- **No impl/content change**: P3.7-content's 11 atomics are unchanged; the canonical gate
  (ruff / ruff format / `mypy --strict` / pytest) is green at `b84d451`.
- **Doc fix (junior, 13f037f)**: `contributing.md` §205 — removed the `mypy --strict .`
  whole-tree form (was overstating scope) and added the explicit note that `plugins/` is not
  in the canonical mypy scope, excluded from the global `[tool.mypy] files` setting.
- **Senior self-attribution carried forward**: PvI-1 originated from the plan's
  "mirror `plugins/demo/`" instruction (atomic 10) meeting mypy's flat-module namespace — a
  latent senior-plan gap, not a junior defect. The ruling resolves it at the gate-definition
  level (the right altitude) rather than reshaping content.

## Re-verification (senior revision session, 2026-06-04)

| Check | Result |
|---|---|
| §205 doc fix landed (canonical `mypy --strict` form + plugins/ scope note) | ✅ 13f037f — `.` removed; plugins/ exclusion stated |
| ruff check | ✅ All checks passed |
| ruff format --check | ✅ 224 files formatted |
| `mypy --strict` (canonical, config `files`) | ✅ Success, 222 source files |
| pytest | ✅ 1653 passed |

PvI-1 resolved per the ruling; plan-vs-impl verdict bumped to `clean` (RC-10 verdict-bump).
Nothing else open — ready for merge close-out.
