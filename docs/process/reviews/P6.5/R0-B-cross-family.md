---
task_id: P6.5
round: R0-B
verdict: needs_architect
findings_count:
  red: 1
  yellow: 2
  green: 6
lens: subprocess-injection (cross-family — same lens that caught P6.1 Bug B)
reviewed_commit: fb68efc (origin/claude/P6.5-impl)
gates_run: ruff ✅ / mypy ✅ / pytest 29/29 ✅ / t9+t12 ✅
spine_verified: byte-identical (gate/_execute_local_call/decide_tier — zero diff vs main)
no_new_llmpurpose: true
---

# P6.5 R0-B cross-family review

## Lens preamble

P6.5 hardens `git_push` (ADR-036 D3-iii, the most-irreversible tool) with two layers:
a `GIT_ALLOW_PROTOCOL` transport allowlist and a configured-remote-name restriction.
The architect explicitly routed dual-lens cross-family review because this is a
subprocess-injection surface — the same lens that caught P6.1 Bug B (a runtime
flag-injection bypass the in-family reviewers missed).

I applied the runtime-integration / attacker-perspective lens: for each check,
ask "how does this fail at 3am when the operator isn't watching?" — trace every
git subprocess path for env coverage, exhaust every syntax-level bypass of the
input-validation checks, and probe for the next `-`/`--` blind spot.

**The P6.5 diff itself is clean** — no new bugs introduced, all four git calls
covered by the transport allowlist, configured-remote enforcement correctly
fail-closed. The 🔴 finding is **pre-existing** on the adjacent banned-flags
check, surfaced because the cross-family lens probes the refspec syntax layer
that the flag-oriented checks don't cover. Same class as P6.1 Bug B: the check
is correct for what it checks, but what it checks is not exhaustive.

## Findings

### 🔴 Y1 — `:branch` deletion refspec bypasses `--delete` ban (pre-existing)

**File:** `src/orchestrator/tools/subprocess_tools.py:417-422`

**Claim:** `branch = ":main"` deletes the remote `main` branch, evading both the
`-`-prefix check (`:main` starts with `:`, not `-`) and the exact-match
banned-flags check (`:main` is not `--delete`). git interprets `:<ref>` as
"delete remote ref" — functionally identical to `--delete <ref>`.

**Confirmed empirically** on git 2.43:
```bash
GIT_ALLOW_PROTOCOL="https:ssh:git:file" git push origin ":main"
# silent success; remote main branch is deleted
```

**Why it matters:** `--delete` is explicitly banned by `_GIT_PUSH_BANNED_FLAGS`
(ADR-036 D3-iii: "no --delete in the fixed argv"). The `:<ref>` syntax is the
same operation via a different syntax — exactly the class of blind spot the
cross-family lens caught in P6.1 Bug B (flag-shape check that doesn't cover all
flag-shapes).

**Pre-existing:** this gap exists on `main` pre-P6.5; P6.5 doesn't widen it. The
banned-flags check and `-` prefix check are original code.

### 🟡 Y2 — `+refspec` force-push bypasses `--force` ban (pre-existing)

**File:** `src/orchestrator/tools/subprocess_tools.py:417-422`

**Claim:** `branch = "+main:main"` is a force-push refspec (`+` prefix means
"allow non-fast-forward"). It passes both checks (doesn't start with `-`, not
in `_GIT_PUSH_BANNED_FLAGS`). Same blind-spot class as Y1 — refspec syntax
carries destructive semantics the exact-match flag check doesn't capture.

**Why it matters:** `--force` / `--force-with-lease` / `-f` are banned, but
`+refspec` is the equivalent operation via refspec syntax. An operator skimming
the confirm dialog sees `branch: +main:main` — the `+` is subtle.

**Pre-existing:** same as Y1.

### 🟡 Y3 — `git remote` list → push race window (P6.5-introduced, low risk)

**File:** `src/orchestrator/tools/subprocess_tools.py:446-461`

**Claim:** Between the `git remote` list call and the `git push` call, a
concurrent process could add or remove a remote, causing the configured-remote
check to operate on stale data. Practical risk is negligible: the prompt-injected
attacker has no filesystem access to run `git remote add`, and the check is
fail-closed (no remote passes if `git remote` fails).

**Suggested investigation:** add a brief comment noting the intentional lack
of a lock (operator-only remote management; the window is not attacker-reachable).

### 🟢 N1 — `GIT_ALLOW_PROTOCOL` env var is real and enforced

Verified via `man git` (listed alongside `GIT_PROTOCOL_FROM_USER`) and
empirically on git 2.43: `ext::` and `fd::` transports are both rejected.
Not a placebo — the transport allowlist is a genuine defense-in-depth layer
that blocks `protocol.ext.allow=always` in gitconfig.

### 🟢 N2 — All four git subprocess paths covered

- `git rev-parse HEAD` (line 393): `scoped_env(extra_env={"GIT_ALLOW_PROTOCOL": …})` ✅
- `git remote` list (line 448-451): `scoped_env(extra_env={"GIT_ALLOW_PROTOCOL": …})` ✅
- `git push` (line 468): `extra_env["GIT_ALLOW_PROTOCOL"] = …` ✅
- `git remote get-url` (line 500): `scoped_env(extra_env={"GIT_ALLOW_PROTOCOL": …})` ✅

Env inheritance verified: `scoped_env()` overlays `extra_env` → `run_scoped_command` → `anyio.open_process(env=env)`. Both `_dispatch` and `_sandbox_dispatch` construct env from `scoped_env(extra_env=extra_env or {})`. No gap.

### 🟢 N3 — Configured-remote restriction correctly fail-closed

- Inline URLs (`https://evil/r`, `git@evil:r.git`) rejected — not in `git remote` output ✅
- `ext::` / `fd::` strings rejected — not a configured name ✅
- Empty/missing remotes → `configured_remotes = set()` → all pushes fail ✅
- `git remote` timeout → `except (SubprocessTimeoutError, OSError): configured_remotes = set()` → fail-closed ✅
- `git remote` non-zero exit → `else: set()` → fail-closed ✅
- Case-sensitive exact match (`origin` ≠ `ORIGIN`) — correct ✅
- `splitlines()` + `strip()` parsing is safe (git remote names cannot contain newlines) ✅
- Remote names starting with `-` are rejected by git itself (`git remote add --foo` fails) — defense-in-depth ✅

### 🟢 N4 — Auto-format noise (no behavior change)

The diff contains mechanical reformatting across 6 tool functions (`_make_run_tests`, `_make_run_lint`, `_make_git_blame`, `_make_git_log`, `_make_git_diff`, `_make_git_push`) — splitting single-line `_sandbox_dispatch`/`_dispatch` calls into multi-line. Zero behavior change; likely ruff/black auto-format. Same in test file (`subprocess.run` calls). Dilutes the security-relevant diff but is harmless.

### 🟢 N5 — Constitution gates green, spine zero-diff

- `tests/tools/test_subprocess_tools.py`: 29 passed (4 new + 3 updated + 22 unchanged) ✅
- `tests/tools/test_constitution.py::test_t9_no_shell_in_subprocess_surface` ✅
- `tests/tools/test_constitution.py::test_t12_git_push_banned_flags` ✅
- `ruff` + `mypy`: clean ✅
- Spine byte-identical: `gate.py` / `scoring.py` / `_execute_local_call` — zero diff ✅
- No new `LLMPurpose` in tools/ ✅

### 🟢 N6 — Happy path regression test passes

`test_git_push_happy_path_local_remote` updated to use `git remote add origin` + `remote="origin"` — correct adaptation to the configured-remote restriction, confirming `origin` push still works.

## Synthesis

Y1 and Y2 cluster: the `_GIT_PUSH_BANNED_FLAGS` exact-match check + `-`-prefix
check together form a **flag-oriented defense** that has a **syntax-level blind
spot** at the refspec layer. `:<ref>` (delete) and `+<refspec>` (force) carry
the same destructive semantics as the banned flags but use different syntax.
This is the same error class as P6.1 Bug B (where the flag-shape check missed
a flag variant) — the cross-family lens caught it because it asks "what are ALL
the ways git can delete a remote branch?" rather than "are the flags correctly
blocked?"

The P6.5 changes are themselves clean and well-tested. The transport allowlist
is comprehensive, the configured-remote restriction is correctly fail-closed,
and the env inheritance chain is intact across all four git subprocess paths.
