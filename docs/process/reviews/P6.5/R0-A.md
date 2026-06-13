---
task_id: P6.5
kind: R0-A-on-impl
surface: product
stage: impl
cycle: 1
reviewed_ref: origin/claude/P6.5-impl @ fb68efc
lens: subprocess-injection threat-probe (cross-family dual-lens; runs beside R0-B)
verdict: needs_architect   # impl is correct + safe to ship on the security axis; 3 🟡 test-integrity / annotation-precision findings warrant an architect routing call (α fix-in-cycle vs β defer)
author: architect-partner
---

# P6.5 R0-A — git_push remote hardening (transport allowlist + configured-remote restriction)

## TL;DR

The hardening is **functionally correct and safe to ship**. Both named vectors are genuinely closed: I verified the transport block empirically (git refuses `ext` under `GIT_ALLOW_PROTOCOL`) and the configured-remote restriction runs on **both** dispatch paths with fail-closed error handling. Spine 0-diff, ADR-037 D2 isolation contract untouched, t9/t12 green, full gate green.

**But two of the three tests the senior plan §4 designated as "fail-on-revert" do not actually fail on revert**, and the load-bearing `file`-in-allowlist choice (senior §5a) is **entirely unguarded**. None of this is a product-code defect — the impl is right — so this is `needs_architect` (route the test work α now / β follow-on), **not** blocking.

## What is verified correct (the security core holds)

- **2a — transport RCE closed (empirically).** `_GIT_ALLOW_PROTOCOL = "https:ssh:git:file"` (`subprocess_tools.py:55`) is overlaid on the push subprocess env (`:468`) and flows through **both** paths — sandbox `_sandbox_dispatch(…, extra_env=extra_env)` and non-sandbox `return _dispatch("git_push", …, extra_env=extra_env)` (`:486`), plus the DEGRADED fall-through (`_dispatch(tool_name, …, extra_env)`, `:173`). Every other git invocation in the module also carries it: HEAD resolve (`:407`), the new `git remote` list (`:444`), and `git remote get-url` (`:503`). I confirmed git's behaviour directly: with `GIT_ALLOW_PROTOCOL=https:ssh:git:file`, `git push <ext-remote>` → `fatal: transport 'ext' not allowed` (denied at the transport layer before any helper spawns). Robust.
- **2b + 2a-via-param — configured-remote restriction on both paths, fail-closed.** The name-check (`:439-459`) is placed **after** the flag/banned-flag checks and **before** the `if posture_resolver is not None` branch, so it guards the non-sandbox `_dispatch` RCE path too. `configured_remotes` is the `git remote` output set on exit 0, else `set()`; `SubprocessTimeoutError`/`OSError` → `set()` (`:451-454`); any non-match → `LocalToolError` (`:455-459`). Empty-set-on-error = fail-closed (every remote rejected). Correct.
- **No regression to existing guards.** The flag-shape rejection (`remote.startswith("-")`) and the 5 banned-flag checks are preserved ahead of the new block. `test_git_push_flag_shaped_*` / `_banned_flag_*` still pass.
- **Spine byte-frozen.** Diff touches only `subprocess_tools.py` + its test + `ADR-036`. `scoring.py` / `profile.py` / the gate / `_execute_local_call` / `autonomy/` are **0-diff** (verified by name-only diff). ADR-037 D2 isolation contract untouched — `_sandbox_dispatch` signature and egress-pinning logic unchanged; the change lives entirely inside `_make_git_push._impl`, below the executor.
- **ADR-036 D3-iii note** present, reads as a *narrowing* (not "solved"), names both layers + cites the P4.3 egress proxy as the hard boundary. Accurate (one wording nit — Y3).
- **No new `LLMPurpose`** (t3 free — `tools/` covered); all new git calls are fixed-argv (t9 green); t12 unaffected.

## Gate results (run independently in an isolated detached worktree, `uv sync --all-extras`)

- `ruff check .` → **All checks passed**
- `mypy` → **Success: no issues in 310 source files**
- `pytest` (full) → **rc=0** (green). Targeted: `tests/tools/test_subprocess_tools.py` + `test_constitution.py` = **52 passed**; all 14 `git_push` nodes pass incl. the 4 new P6.5 tests; `t9_no_shell_in_subprocess_surface` + `t12_git_push_argv_discipline` green.

## Findings

### 🟡 Y1 — happy-path test passes on a *failed* push; the `file`-allowlist choice is unguarded

`test_git_push_happy_path_local_remote` pushes `{"remote":"origin","branch":"main"}` but sets the repo up with bare `git init src` (no `-b main`). On the CI git (2.43.0, no `init.defaultBranch`) the default branch is **`master`**, so the tool runs `git push origin main` → `error: src refspec main does not match any` → **real `exit_code=1`**. The test asserts only `assert "exit_code=" in result.content`, which matches `exit_code=1` → **the test passes although the push failed.**

Two compounding consequences, both verified empirically:
1. **Criterion 3 ("origin push still works", `exit_code=0`) is not actually verified.** The push never succeeds in this test.
2. **The `file`-in-`_GIT_ALLOW_PROTOCOL` decision — senior §5a's explicitly load-bearing call — is exercised by *zero* tests.** The refspec error precedes git's protocol allow-check: `GIT_ALLOW_PROTOCOL="https:ssh:git" git push origin main` → `src refspec main does not match any` (exit 1), whereas with the *correct* branch `… push origin master` → `fatal: transport 'file' not allowed` (exit 128), and `…:file … push origin master` → success (exit 0). So if someone took the `https:ssh:git` (drop-`file`) option the senior surfaced in §5a, **this test would stay green** — the one change most likely to regress the happy path is uncaught.

The **impl is correct** — a real `git_push(remote="origin", branch="<real-branch>")` pushes fine (proven: exit 0 with the correct branch), and real callers resolve the branch from HEAD. This is a test defect, not a product bug. Fix is a 2-line test edit: init with `-b main` (or push the actual default branch) **and** assert `exit_code=0`.

**Lean: α (fix in-cycle).** It's test-only, and for a security slice the regression guard on the load-bearing allowlist set should bite.

### 🟡 Y2 — the ext defense-in-depth test is a false-pass

`test_git_push_ext_protocol_blocked_by_allowlist` configures `evil → "ext::sh -c 'touch {pwned}'"`, pushes `remote="evil"`, and asserts `not pwned.exists()`. The transport block it documents **is real** (Y-positive: proven `fatal: transport 'ext' not allowed`). But the *test* doesn't prove it: git's `ext::` transport space-splits its argv with no shell and no quote processing, so `ext::sh -c 'touch X'` becomes argv `["sh","-c","'touch","X'"]` → `sh -c "'touch"` → "Bad command", **no file created — even with `ext` allowed** (I verified: `git -c protocol.ext.allow=always push evil` → no PWNED). So "assert no PWNED" holds regardless of `GIT_ALLOW_PROTOCOL`; the test would pass on a revert of the transport allowlist.

Mitigant: the allowlist's **wiring** is independently guarded — `test_git_push_allow_protocol_in_env` asserts `GIT_ALLOW_PROTOCOL == _GIT_ALLOW_PROTOCOL` in the subprocess env and *does* fail-on-revert of the `:468` line. So the property is not unguarded, only this behavioural demonstration is hollow. Suggested strengthening: assert the protocol-denied signal instead of a side-effect that never fires — e.g. `"not allowed" in result.content` (true fail-on-revert: without the allowlist the error is "Bad command", not "transport 'ext' not allowed").

**Lean: α (fix in-cycle), lower urgency than Y1** — the env-presence test already guards the wiring, so this is test-honesty, not a coverage hole.

### 🟡 Y3 — annotation precision: "operator-configured" overstates; `apply_edit` → `.git/config` re-opens 2b (out of scope, net-improvement)

The name-restriction assumes `git remote` reflects only **operator**-configured remotes. But `apply_edit`'s `_check_path` enforces *containment under the repo root*, not a `.git/`-deny — and `.git/config` sits under the root. An in-sandbox agent holding both `apply_edit` and `git_push` could write a remote `evil → https://attacker.example` into `.git/config`, then `git_push(remote="evil")` passes the name-check and, on the sandbox path, `_resolve_git_remote_host` pins egress to the agent-chosen host — i.e. the 2b exfil vector re-opens via config-poisoning rather than the inline-URL param.

Scope/severity calibration: this is a **different vector** (config-poisoning) than the 2a/2b *param* vectors P6.5 was ratified to close, it is **out of P6.5's scope**, and P6.5 is a strict **net improvement** (pre-P6.5, any inline URL worked with no config step at all). git_push is rev-1 HARD → always human-confirmed, and the confirm surfaces `remote`. So **not blocking**. The only in-artifact issue: the ADR-036 D3-iii annotation's phrase *"NARROWED to operator-configured remotes"* is slightly optimistic — strictly it's "configured remotes," which an in-sandbox `apply_edit` can extend. (The annotation does already name the egress proxy as the hard boundary, which is the honest backstop.)

**Lean: note + β.** A one-word annotation tweak ("configured" not "operator-configured", or an explicit apply_edit caveat) is cheap; the underlying follow-on (e.g. `.git/`-deny in `apply_edit`, or resolving remotes from a source git can't self-mutate) is its own backlog item, not this slice. Surfacing for awareness — same exfil-by-remote lens the brief itself used.

## Verdict & routing question

**`needs_architect`.** The hardening is correct and safe — ship-worthy on the security axis. The open call is purely about test integrity on a security slice:

- **Y1** (happy-path passes on failure; `file`-allowlist unguarded) — lean **α** (2-line test fix).
- **Y2** (ext test false-pass) — lean **α**, lower urgency (wiring already guarded by the env test).
- **Y3** (annotation "operator-configured" overstates; apply_edit config-poison re-opens 2b, out of scope) — lean **note + β** follow-on.

Architect: route Y1/Y2 **α (fix in this cycle)** or **β (merge, test-hardening follow-on)**? Y3 is a wording tweak + backlog item, your call. R0-B runs in parallel on the same surface; synthesize when both land.
