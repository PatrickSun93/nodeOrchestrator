---
task_id: P6.5
round: R0-B
cycle: 2
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 4
lens: subprocess-injection (cross-family — refspec-bypass re-verification + attacker-perspective exhaustiveness)
reviewed_cycle_1_commit: fb68efc
reviewed_cycle_2_commit: 3ae8042 (origin/claude/P6.5-impl)
gates_run: ruff ✅ / mypy ✅ / pytest 32/32 subprocess_tools + 23/23 constitution ✅ / t9+t12 ✅
spine_verified: byte-identical (gate/_execute_local_call/decide_tier — zero diff vs main)
no_new_llmpurpose: true
cycle_1_verdict: blocking (1🔴 R1 refspec-delete + 1🟡 R2 refspec-force)
cycle_1_findings_resolved:
  R1: "✅ fixed — branch :refspec rejected via startswith(':')"
  R2: "✅ fixed — same check covers +refspec via startswith('+')"
  R0A-Y1: "✅ fixed — happy-path test asserts exit_code=0"
  R0A-Y2: "✅ fixed — ext:: test asserts 'not allowed'"
  R0A-Y3: "✅ fixed — ADR-036 wording + apply_edit caveat → task #109"
---

# P6.5 R0-B cross-family review — cycle 1 + cycle 2

## Cycle 1 (2026-06-14, fb68efc) — summary

Cycle 1 reviewed the G1 impl (transport allowlist + configured-remote restriction).
The G1 diff itself was clean — all four git subprocess paths covered by
`GIT_ALLOW_PROTOCOL`, configured-remote enforcement correctly fail-closed, spine
byte-identical, gates green. One 🔴 found on adjacent pre-existing code:

- **🔴 R1 — `branch=":main"` deletion refspec bypass.** `:refspec` carries
  the same destructive semantics as `--delete` (which IS banned) but uses
  different syntax, evading both the `-`-prefix check and the
  `_GIT_PUSH_BANNED_FLAGS` exact-match check. Empirically confirmed on git 2.43.
- **🟡 R2 — `branch="+main:main"` force-push refspec bypass.** Same blind spot;
  `+refspec` = force-push, evading the `--force` ban.
  Suggested fix: reject `branch` values starting with `:` or `+` before argv build.

Verdict: blocking (1🔴). Architect routed α — fix R1/R2 + R0-A Y1/Y2 test-honesty
+ Y3 wording in a single rework cycle.

## Cycle 2 (2026-06-14, 3ae8042) — re-review

### Diff scope

`git diff 88ac9bd..origin/claude/P6.5-impl` — 3 files, 74 insertions, 4 deletions:

| File | Change |
|---|---|
| `src/orchestrator/tools/subprocess_tools.py` | +5 lines: `:`/`+` prefix check at `:433-438` |
| `tests/tools/test_subprocess_tools.py` | +67/-4: 3 new tests + 3 assertion fixes |
| `docs/decisions/ADR-036-mutation-local-tools.md` | 1-line wording edit + apply_edit caveat |

### 🔴 R1/R2 — refspec bypass fix

The fix adds a single guard clause before argv construction (`subprocess_tools.py:433-438`):

```python
if branch.startswith(":") or branch.startswith("+"):
    raise LocalToolError(
        f"git_push: branch {branch!r} uses a refspec prefix "
        "(: deletion / + force-push); only plain branch names are accepted"
    )
```

**Status: ✅ FIXED.** The check blocks both `:refspec` (delete) and `+refspec` (force).
Empirically confirmed on git 2.43. The fix is surgical (5 lines), correctly placed
after the `-`-prefix check and before argv construction, with zero effect on the
banned-flags check or the env/argv build below.

### Attacker-perspective exhaustiveness audit

I enumerated every git refspec syntax variant that carries destructive or
potentially-destructive semantics and tested each empirically against git 2.43
to determine whether the combined check-set (`-`-prefix → `:`/`+`-prefix →
`_GIT_PUSH_BANNED_FLAGS` exact-match) blocks it.

**Blocked vectors (destructive, caught by one or more checks):**

| Variant | Git behavior | Blocked by |
|---|---|---|
| `:main` | Delete remote `main` | `startswith(":")` ✅ |
| `:refs/heads/main` | Delete (full ref) | `startswith(":")` ✅ |
| `+main:main` | Force-push | `startswith("+")` ✅ |
| `+refs/heads/*:refs/heads/*` | Force-push all branches | `startswith("+")` ✅ |
| `--force`, `--force-with-lease`, `-f`, `--mirror`, `--delete` | Destructive flags | `_GIT_PUSH_BANNED_FLAGS` ✅ |
| `-f`, `--foo`, any `-`-prefixed | Flag injection | `startswith("-")` ✅ |

**Whitespace/control-char bypass attempts — practically inert:**

| Variant | Git result | Why inert |
|---|---|---|
| ` :main` (leading space) | `error: src refspec does not match any` | git treats space as part of refspec name; no deletion |
| `\t:main` (leading tab) | Same error | Same mechanism |
| `\n:main` (leading newline) | Same error | Same mechanism |

The hypothesis that git silently strips leading whitespace is **falsified**.
Remote ref confirmed intact after all three attempts.

**Correctly permitted (normal push, not destructive):**

| Variant | Git behavior | Why permitted |
|---|---|---|
| `main` | Normal push | Plain branch name — intended use |
| `main:other` | Create `other` on remote | Normal `src:dst` push; no force/delete |
| `HEAD:main` | Push HEAD to `main` | Normal push; no force/delete |
| `refs/heads/main:refs/heads/other` | Full-ref push | Same as `main:other` with explicit refs |

### 🟡 N1 — Glob refspec passes all checks (pre-existing edge case)

**Claim:** `branch="refs/heads/*:refs/heads/*"` starts with `r` (no prefix match),
is not in `_GIT_PUSH_BANNED_FLAGS`, and is accepted by git as a valid refspec.
In a multi-branch repo, this pushes ALL branches. The code's error message says
"only plain branch names are accepted" — but the check only blocks `:` and `+`
prefixes, not glob patterns.

**Why 🟡, not 🔴:** the glob refspec is non-destructive:
- No `+` prefix → non-fast-forward branches are rejected at the remote
- No `--prune` → no deletion of remote branches missing locally
- No `--mirror` → tags and non-branch refs are NOT pushed
- HARD confirm dialog surfaces the `branch` value — glob is visually recognizable

The `--mirror` ban is about comprehensive push-all-refs with force semantics.
A non-force glob pushes all branches but fails on any that would require force —
it lacks the destructive payload. The `+refs/heads/*:refs/heads/*` force-glob
variant IS caught by the `+`-prefix check.

**Pre-existing:** this edge case predates both cycle-1 and cycle-2. Cycle-2's
`+`-prefix check does block the destructive variant.

**Suggested investigation:** either tighten the check (reject `*`, `?`, `[` in
`branch`) or narrow the error message ("only plain branch names" → "no refspec
prefixes (: / +)"). The architect may also route this as "wontfix" — the HARD
confirm dialog makes the value visible to the operator.

### R0-A test-honesty fixes — verified

| R0-A finding | Status | Evidence |
|---|---|---|
| Y1 — vacuous happy-path test | ✅ Fixed | `assert "exit_code=0" in result.content` (was `"exit_code=" in`) |
| Y2 — ext:: false-pass test | ✅ Fixed | `assert "not allowed" in result.content` (was `"exit_code=" in`) |
| Y3 — ADR wording | ✅ Fixed | "configured remotes" + `apply_edit` caveat → task #109 |

New regression tests added in cycle-2:
- `test_git_push_transport_allowlist_set` — pins `file` in, `ext` out ✅
- `test_git_push_refspec_delete_rejected` — `:main` → `LocalToolError` + remote ref intact ✅
- `test_git_push_refspec_force_push_rejected` — `+main:main` → `LocalToolError` ✅

The refspec-delete test is particularly well-constructed: it pushes `main` to a
bare repo, attempts `:main`, asserts rejection, then verifies the remote ref
still exists via `git ls-remote`. This is a genuine fail-on-revert test.

### Regressions

None. The cycle-2 product-code change is exactly 5 lines — a single `if` block.
No existing test broke; the 3 updated assertions are all within the tests that
the plan identified as needing changes.

### 🟢 Positive

- **🟢-1 (spine byte-freeze held).** `gate.py`, `_execute_local_call`, `decide_tier`
  — zero diff vs main. Same as cycle-1.
- **🟢-2 (constitution gates silent).** t9 (no-shell) and t12 (banned-flags)
  pass with zero test code changes. The refspec check runs before argv construction,
  so no new shell/flag surface.
- **🟢-3 (no new LLMPurpose).** Only `content-gen` purposes in the module.
- **🟢-4 (gates all green).** ruff ✅, mypy ✅, pytest 32/32 subprocess_tools
  + 23/23 constitution ✅. Run in isolated detached worktree at 3ae8042
  (`uv sync --all-extras`).

## Gates (cycle-2, worktree at 3ae8042)

| Gate | Result |
|---|---|
| `ruff check` on changed files | ✅ clean |
| `mypy --strict` on changed files | ✅ clean |
| `pytest tests/tools/test_subprocess_tools.py` | 32/32 ✅ |
| `pytest tests/tools/test_constitution.py` | 23/23 ✅ |
| Spine diff vs main (`gate.py`, `_execute_local_call`, `decide_tier`) | 0 bytes |

## Synthesis

Cycle-2 is a correct, surgical fix. The `:`/`+`-prefix check, combined with the
existing `-`-prefix and banned-flags checks, blocks every destructive refspec
variant I could enumerate. Whitespace/control-character bypass attempts are
practically inert — git itself rejects them as invalid refspecs. The test-honesty
fixes make the flagged tests genuinely bite on revert.

The one 🟡 (glob refspec) is pre-existing, non-destructive (no force-no-delete),
and bounded by the HARD confirm dialog. The architect may close it as accepted
residual, tighten the check, or narrow the error message.

**Recommendation:** merge as-is. The cycle-1 🔴 is provably closed with thorough
defense. The 🟡 is an edge case the architect can route independently — it does
not block closing P6.5.
