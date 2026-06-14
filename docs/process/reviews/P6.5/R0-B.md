---
task_id: P6.5
round: R0-B
verdict: blocking
findings_count:
  red: 1
  yellow: 1
  green: 4
lens: subprocess-injection (cross-family — same lens that caught P6.1 Bug B)
reviewed_commit: fb68efc
spine_verified: byte-identical (gate/_execute_local_call/decide_tier — zero diff vs main)
gates:
  ruff: pass
  mypy: pass
  pytest_subprocess: 29/29
  pytest_constitution_t9_t12: pass
no_new_llmpurpose: true
---

# P6.5 R0-B cross-family review

## Lens

Subprocess-injection / attacker-perspective — same lens that caught P6.1 Bug B.
For every input-validation check, exhaust every syntax-level bypass: what are
ALL the ways git can express "delete a remote branch" or "force-push," not
just the ways the flag-oriented checks cover.

## Findings

### 🔴 R1 — refspec deletion bypass: `branch=":main"` evades `--delete` ban

**Severity:** high. The banned-flags defense (`_GIT_PUSH_BANNED_FLAGS`) blocks
`--delete` by exact string match, and a separate `startswith("-")` check blocks
flag-shaped values. Both checks are in `subprocess_tools.py:417-422` (pre-P6.5
code, unchanged by this diff).

`branch = ":main"` passes both:
- `":main".startswith("-")` → `False` (starts with `:`, not `-`)
- `":main" in _GIT_PUSH_BANNED_FLAGS` → `False` (`:main` ≠ `--delete`)

argv becomes `["git", "push", "origin", ":main"]`. git interprets `:<ref>` as
"delete the remote ref" — functionally identical to `--delete <ref>`, which IS
banned.

**Empirical confirmation (git 2.43):**

```
$ git push origin ":main"
 - [deleted]         main
```

The remote `main` branch is silently deleted. No error, no rejection.

**Pre-existing:** this gap exists on `main` pre-P6.5. P6.5 does not introduce
or widen it. But the cross-family lens caught it because it probes the refspec
layer, not the flag layer — exactly the class of blind spot that P6.1 Bug B
was (a flag-shape check that missed a flag variant).

**Suggested fix direction:** add a third input-validation rule before the
argv is built — reject `branch` values starting with `:` (deletion refspec)
and `+` (force-push refspec). Minimal, surgical, covers the refspec syntax
surface. Example guard at line ~415:

```python
if branch.startswith(":") or branch.startswith("+"):
    raise LocalToolError(
        f"git_push: branch {branch!r} uses a refspec prefix "
        "(: deletion / + force-push); only plain branch names are accepted"
    )
```

This would close both R1 and R2 (see below) in two lines, zero new dependencies.

### 🟡 R2 — refspec force-push bypass: `branch="+main:main"` evades `--force` ban

Same blind spot, different refspec operator. `branch = "+main:main"`:
- Does not start with `-` → passes flag-shape check
- Not in `_GIT_PUSH_BANNED_FLAGS` → passes exact-match check

git interprets `+refspec` as "allow non-fast-forward update" — functionally
identical to `--force` for that refspec.

**Suggested fix:** covered by the same `:`/`+` guard proposed in R1.

### 🟢 N1 — P6.5 diff itself is clean (no new bugs)

`GIT_ALLOW_PROTOCOL="https:ssh:git:file"` is a real git env var (confirmed
via `man git` and empirical test on git 2.43). `ext::` and `fd::` transports
are both rejected by git when this var is set.

Coverage across all four git subprocess paths in the module:

| call | line | GIT_ALLOW_PROTOCOL |
|---|---|---|
| `git rev-parse HEAD` | ~393 | ✅ `scoped_env(extra_env={...})` |
| `git remote` (list) | ~448 | ✅ `scoped_env(extra_env={...})` |
| `git push` | ~468 | ✅ `extra_env["GIT_ALLOW_PROTOCOL"] = ...` |
| `git remote get-url` | ~500 | ✅ `scoped_env(extra_env={...})` |

Env inheritance: `scoped_env()` → `extra_env` overlay → `run_scoped_command` →
`anyio.open_process(env=env)`. Both `_dispatch` and `_sandbox_dispatch` build
env from `scoped_env(extra_env=extra_env or {})`. Intact across both code paths.

### 🟢 N2 — Configured-remote restriction correctly fail-closed

- Inline URLs (`https://evil/r`, `git@evil:r.git`) are not in `git remote`
  output → rejected ✅
- `ext::` / `fd::` strings are not configured remote names → rejected ✅
- Case-sensitive match (`origin` ≠ `ORIGIN`) ✅
- `git remote` failure/timeout → `configured_remotes = set()` → all pushes
  fail-closed ✅
- Empty output → `splitlines()` of `""` → `[]` → `set()` → fail-closed ✅
- Remote names starting with `-` are rejected by git itself (`git remote add
  --foo` fails) — defense-in-depth, no practical gap ✅

### 🟢 N3 — Gates all green, spine byte-identical

- `tests/tools/test_subprocess_tools.py`: 29 passed (4 new P6.5 tests + 3
  updated + 22 unchanged)
- `test_t9_no_shell_in_subprocess_surface` ✅
- `test_t12_git_push_banned_flags` ✅
- ruff / mypy: clean
- Spine: `gate.py` / `scoring.py` / `_execute_local_call` — zero diff vs main
- No new `LLMPurpose` in tools/

### 🟢 N4 — Happy-path regression confirmed

`test_git_push_happy_path_local_remote` updated from inline `remote=str(bare)`
to `git remote add origin <bare>` + `remote="origin"` — pushes succeed through
the configured-remote check, confirming no regression.

## Synthesis

R1/R2 are a **syntax-level blind spot** in `_GIT_PUSH_BANNED_FLAGS`: the check
blocks destructive operations by matching literal flag strings (`--delete`,
`--force`) and rejecting `-`-prefixed values, but git's refspec syntax provides
alternate spellings (`:ref` = delete, `+ref` = force) that carry the same
destructive semantics without triggering either check.

This is the same error class as P6.1 Bug B, where a flag-shape check missed a
flag variant. The P6.5 diff itself is clean and well-tested; the finding is on
adjacent pre-existing code that the cross-family lens was dispatched to probe.

**Verdict rationale:** `blocking` because R1 is a confirmed 🔴 — a
prompt-injected agent can delete remote branches despite the explicit `--delete`
ban, and the `:` prefix is subtle enough that a user skimming the HARD-confirm
dialog may not recognize it as a deletion instruction. The fix is surgical
(two additional `startswith` guards on `branch`), does not touch the spine,
and can ride as a P6.5 scope expansion or a follow-on atom.
