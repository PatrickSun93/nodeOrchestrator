---
task_id: P3.7-content
kind: plan-vs-impl
cycle: 1
reviewer: senior
verdict: needs_architect
reviewed_branch: claude/P3.7-content-impl
reviewed_head: b84d451
plan: docs/process/senior-plans/P3.7-content.md
gate_results:
  ruff_check: pass
  ruff_format_check: pass
  mypy_strict_canonical: pass        # files=["src","tests"] per pyproject [tool.mypy]; 222 files
  mypy_strict_dot: fail              # `mypy --strict .` (contributing.md §205 form): duplicate module tools_impl
  pytest: pass                       # 1653 passed
summary_note: >-
  Impl is faithful to all 11 atomics and discriminating-test bar; one finding (PvI-1):
  `mypy --strict .` (the dot/whole-tree form documented in contributing.md §205) is RED on
  a duplicate top-level module `tools_impl` (plugins/demo vs the new plugins/context). The
  canonical pyproject-scoped gate (files=src,tests) is GREEN. Resolution needs an architect
  ruling on mypy scope — surfaced, not self-decided.
---

# Plan-vs-impl — P3.7-content

## Verdict: `needs_architect`

The impl is **faithful** to `senior-plans/P3.7-content.md` across all 11 atomics, and every
new unit ships a genuinely **discriminating** test (not "renders something"). The constitutional
carry-forward held by construction. **One finding (PvI-1)** requires an architect ruling on the
mypy gate's scope — see §3. Everything else is clean.

## 1. Independent gate run (this review)

Run on `claude/P3.7-content-impl @ b84d451`, full suite:

| Gate | Command | Result |
|---|---|---|
| ruff check | `uv run ruff check .` | ✅ All checks passed |
| ruff format | `uv run ruff format --check .` | ✅ 224 files formatted |
| mypy (canonical) | `uv run --extra api mypy --strict` | ✅ Success, 222 source files (pyproject `[tool.mypy] files=["src","tests"]`) |
| **mypy (whole tree)** | `uv run --extra api mypy --strict .` | ❌ **FAIL** — see PvI-1 |
| pytest | `uv run --extra api pytest` | ✅ **1653 passed**, 1 warning |

The junior's local "gates green" almost certainly came from the canonical (src+tests) scope,
which is green; the `.`-form red is invisible unless the dot is passed (consistent with the
standing "junior gates can be src-scoped" caution).

## 2. Plan fidelity — per atomic

| Atomic | Faithful? | Discriminating test verified |
|---|---|---|
| 1 `synthesizer` (research/code_review/idea_validation) | ✅ | loaded+valid; present in 3 declared rosters; `speak=True` on DECISION in each; **absent** from bug_fix & free_chat rosters |
| 2 `planner` (bug_fix/code_review/idea_validation) | ✅ | speaks on diagnosed/reviewing/pitching; absent from research & free_chat |
| 3 `verifier` (bug_fix/code_review) | ✅ | triggers `fix_proposed` (real bug_fix state) + `approved` (real code_review state) — both reachable, no dead trigger; absent from research & idea_validation |
| 4 `mentor` (free_chat/idea_validation) | ✅ | speaks on USER_INPUT in both; absent from research & bug_fix |
| 5 business `idea-validation-rubric` | ✅ | stem==id, `category: business` (fills empty literal); matches idea_validation; **rejected** (`room_type_mismatch`) for code_review & research |
| 6 engineering `code-review-checklist` | ✅ | matches code_review; rejected for research & bug_fix |
| 7 general `facilitation-norms` | ✅ | matches free_chat; rejected for bug_fix & research |
| 8 `memory` connector | ✅ | read_graph/search_nodes rev10→AUTO_EXECUTE; create_entities rev1→HARD_CONFIRM; **delete_entities (unlisted)→UnknownToolError→tier None** |
| 9 `sqlite` connector | ✅ | read_query/list_tables→AUTO; write_query/create_table→HARD_CONFIRM; **drop_table (unlisted)→UnknownToolError** |
| 10 `context` plugin | ✅ | merges role+skill+tool_impl; host-pre-classify `context_summary`(rev10)→AUTO; plugin-classify-only `annotate_context`→**caps to rev 0→HARD_CONFIRM** (ADR-029 D5); fail-closed bad-manifest |
| 11 `insights` plugin | ✅ | different mix (skill + mcp_servers ref, no tool_impls); manifest+mcp yaml validate; fail-closed **name-collision** (insights_db) → refused, host unchanged |

**Pure-additive / carry-forward checks (all hold):**
- **No new `LLMPurpose`**: `git diff` for `LLMPurpose`/`AGENT_RESPONSE`/`content-gen` → empty. Agent responses reuse the frozen content-gen path; activation stays code `should_agent_speak`.
- **Frozen loaders untouched**: no edit to `agents/loader.py` / `skills/loader.py` / `templates.py` `load_room` logic / `mcp/config.py` / plugin loader. `templates.py` change is data-only (roster lists).
- **Gate/executor untouched**: connectors route through the existing ADR-027 pre-classify-allowlist; the `tier is None` on unlisted tools is the existing fail-closed path, re-exercised.
- **Existing-test edits are additive tightening, not weakening**: `test_loader.py` still asserts exact `set(agents) == {…10…}` (no `len` relaxation); `test_templates.py` bumps roster/missing/count assertions to the new rosters; `test_config_loader.py` adds the 4 new ids. `config/tools.yaml` adds only `context_summary: rev 10` (host-authoritative classification for atomic 10, ADR-029 D5/D7).

## 3. Finding

### PvI-1 — `mypy --strict .` duplicate-module collision (scope ruling needed)

**Evidence.** `uv run --extra api mypy --strict .` fails:
```
plugins/demo/tools_impl.py: error: Duplicate module named "tools_impl"
  (also at "./plugins/context/tools_impl.py")
```
`plugins/context/tools_impl.py` (new, atomic 10) collides with the pre-existing
`plugins/demo/tools_impl.py` — two top-level modules of the same name in mypy's flat
namespace. **Canonical-scope mypy (`files=["src","tests"]`) is green**; the failure only
surfaces when the whole tree is checked with the `.` argument.

**Why it's a finding, not a junior defect.** The plan (atomic 10) said *"mirror `plugins/demo/`"*
and listed `tools_impl.py` as a where-path. The junior followed that faithfully; the collision is
an **emergent interaction** between the mirror-the-demo convention and mypy's flat-module
namespace that **the plan did not anticipate** (senior gap — owned here). So this is plan-implied
drift, not an acceptance-criterion miss.

**Why `needs_architect`, not auto-fixed.** Resolution depends on a scope decision that is the
architect's (dev-harness/process call), and any fix reaches **beyond pure content**:
- **(A) plugins are deliberately out of the typed surface** — pyproject `[tool.mypy] files=["src","tests"]` is authoritative; Posture-A plugin code is operator-placed, dynamically loaded, not part of the typed product. Then the impl is **green under the real gate** and the action is a one-line doc fix: contributing.md §205's `mypy --strict .` overstates scope vs the pyproject config. (No code change; the finding is benign.)
- **(B) plugins should be type-checked** — then the collision must be resolved (e.g. mypy `explicit_package_bases`/`namespace_packages`, per-plugin `__init__.py`, or a unique impl-module name + manifest reference update). Each is a small config/structure decision with trade-offs — not content.

CI workflow files were not found under `.github/workflows`, so I could not confirm which
invocation CI runs; the discrepancy is between the pyproject config and the contributing.md doc.

**Recommendation (architect's call):** rule (A) vs (B). If (A), no impl change — optionally
queue the §205 doc-scope clarification. If (B), dispatch the collision fix as a follow-up atomic.
I did **not** pick one — gate scope is a dev-harness decision, and a fix would breach the
pure-content boundary.

## 4. Bottom line

11/11 atomics faithful; discriminating-test bar met on every surface; carry-forward intact;
canonical gate + 1653 tests green. The single open item is PvI-1 (mypy scope ruling). Verdict
`needs_architect` routes that one decision; nothing here is blocking the content itself.
