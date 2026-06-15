---
task_id: P6.9
review: plan-vs-impl
reviewer: senior
verdict: clean
impl_ref: origin/claude/P6.9-impl @ 78d00fe
plan_ref: docs/process/senior-plans/P6.9.md
findings_count:
  red: 0
  yellow: 0
  green: 2          # one per atom, both atomic-faithful
notes_count: 1       # NN-1 cosmetic message redundancy (#110), non-blocking
---

# P6.9 plan-vs-impl — git_push glob-reject (#110) + apply_edit `.git/`-deny (#109)

**Verdict: clean.** Both atoms are faithful to `senior-plans/P6.9.md`. No
plan-external expansion, spine byte-frozen, fail-on-revert wired, ADR-036 D3-i
amendment inscribed in place with the dated marker. No new ADR (correct: #109 is
an in-place amendment of the already-Accepted ADR-036 D3-i; #110 is D3-iii
input-validation, no contract touch).

Impl is exactly two atom commits on top of `d9eefb8` (`b1d78d4` #110, `78d00fe`
#109) — **no stray `workflow advance` commit** on the branch, one atomic = one
commit per RC-17.

## Scope guard (5-surface)

Diff touches only the six files the plan names:
`subprocess_tools.py`, `mutation_tools.py`, `ADR-036`, `test_constitution.py`
(t11+t12), `test_mutation_tools.py`, `test_subprocess_tools.py`. Spine grep
(`_execute_local_call` / `LLMPurpose` / autonomy gate / confirm-then-execute) →
**zero hits in the diff.** No new `LLMPurpose`. `_check_path` (shared with read
tools) **not** touched — the `.git/`-deny is apply_edit-local as the plan pins.

---

## 🟢 G1 — P6.9-110: git_push reject glob (`*`) + accurate guard message — FAITHFUL

`subprocess_tools.py:433-448`. Against the plan's acceptance criteria:

- **`*` anywhere → `LocalToolError`** ✓ — `if "*" in branch:` added after the
  `:`/`+` prefix guard. Covers `refs/heads/*:refs/heads/*`, `*`, `main:*`
  (tests: `test_git_push_glob_refspec_rejected`,
  `test_git_push_glob_star_alone_rejected`, `test_git_push_glob_in_src_dst_rejected`).
- **`main` (plain) still accepted** ✓ — neither guard fires on a plain name.
- **`main:other` (simple `src:dst`) still accepted** ✓ — no `:`/`+` prefix, no
  `*`; passes the refspec guard (`test_git_push_simple_src_dst_not_over_blocked`
  asserts the guard does **not** fire, real push to a bare repo).
- **Reworded message no longer claims "only plain branch names"** ✓ — both the
  `:`/`+` guard and the new `*` guard now state "refspec prefixes (: delete /
  + force) and glob (*) refspecs are rejected; plain branch names and simple
  src:dst are accepted." The two pre-existing tests
  (`test_git_push_refspec_delete_rejected` / `…force_push_rejected`) were
  updated from `match="only plain branch names are accepted"` to
  `match=r"glob \(\*\) refspecs are rejected"` — the shared wording means the
  same substring matches both guards.
- **t12 extended** ✓ — asserts `refs/heads/*:refs/heads/*` → error mentioning
  `glob`, and `main:other` → not blocked by the glob/prefix guard.
- **fail-on-revert** ✓ — removing the `*` check makes the three glob tests +
  the t12 glob case fail (`pytest.raises` no longer satisfied); the
  `main:other` accept-case stays green.
- **Out-of-scope respected** ✓ — no `src:dst` constraining beyond glob, no
  `remote`-side change, the P6.5 `:`/`+`/banned-flag/configured-remote checks
  left intact (only `*` added + message reworded).

## 🟢 G2 — P6.9-109: apply_edit deny `.git/` + ADR-036 D3-i amendment + t11 — FAITHFUL

`mutation_tools.py:168-178`, `ADR-036` D3-i + residuals, `test_constitution.py`
t11. Against the plan's acceptance criteria:

- **apply_edit-local, post-`_check_path`, pre-write** ✓ — the check sits
  immediately after `dest = _check_path(...)` and before `dest.parent.mkdir` /
  the temp-create. `_check_path` untouched → read tools unaffected (plan §5
  push-back point honored).
- **Resolved-`dest` first-component test** ✓ —
  `parts = dest.relative_to(resolved_root).parts; if parts and parts[0] == ".git"`.
  Denies `.git` itself and anything under it; because `dest` is post-resolve,
  an in-sandbox symlink into `.git/` is caught too.
- **`.git/config` → error, file unchanged** ✓ (t11 + `test_apply_edit_git_config_denied`
  both assert the original content survives — check precedes write, no temp/partial).
- **`.git/hooks/pre-push` → error** ✓ — whole-`.git/` deny, not just `config`
  (t11 + `test_apply_edit_git_hooks_denied`).
- **Normal in-root write still succeeds** ✓ — `workspace.txt` written + present
  in result (t11 + `test_apply_edit_git_deny_not_over_broad`); deny proven
  non-over-broad.
- **ADR-036 D3-i amended in place** ✓ — the D3 §(i) "Check-time containment"
  bullet gains a `**[Annotated P6.9 2026-06-15: …]**` clause inscribing the
  first in-root denylist carve-out ("contained-in-root ⇒ writable, *except* the
  control-plane `.git/`"), apply_edit-local, deny scope = `.git/` only. The
  residuals row (line 138) also carries a P6.9 marker. No renumber / restructure.
- **fail-on-revert** ✓ — reverting the deny makes the t11 `.git/config` +
  `.git/hooks` asserts fail; the normal-write success case stays green.
- **Out-of-scope respected** ✓ — **no `.hg`/`.svn` expansion** (deny is the
  literal `.git` component only), no operator-configurable denylist, no
  case-insensitive `.GIT` handling, no `_check_path` change, no git_push change.

---

## Notes (non-blocking)

- **NN-1 (cosmetic):** the reworded `:`/`+` guard message is mildly redundant —
  it opens with `"(: delete / + force);"` and then repeats `"refspec prefixes
  (: delete / + force) and glob (*) refspecs are rejected"`. Accurate and
  satisfies the AC (states what is rejected + accepted, no longer over-claims
  "only plain branch names"); the duplication is purely stylistic. Not worth a
  rev — flag for awareness only.

## Gate status

Not re-run here (review stays on `main`; switching the shared working tree to
the impl branch is avoided per RC). Gate execution is the junior's attested
responsibility per the plan §4 (`ruff` + `mypy` + `pytest` over the `tools/`
test packages). If the architect wants an independent gate run, dispatch it on
a detached worktree (`uv sync --all-extras` first) rather than a shared-dir
checkout.

**Recommendation:** accept → merge. No blocking findings; no architect decision
outstanding (deny scope / ADR vehicle / direction (a) all pre-ratified in the
brief).
