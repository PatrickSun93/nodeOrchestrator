# External R0-B prompt — P4.2-B3 (subprocess local tools) — MANDATORY dual-lens

> **Dispatch context.** `requires_cross_family_review: true` (ratified; P4-roadmap §8 — B3 is in the heavy set: *"the c2 env-leak class"*). You are the **cross-family** reviewer (DeepSeek via the role-rewriting proxy). Review the **impl branch** against ADR-034 (`docs/decisions/ADR-034-subprocess-local-tools.md`), the senior plan (`docs/process/senior-plans/P4.2-B3.md`), and the brief (`docs/process/architect-briefs/P4.2-B3.md`). This is a plan-stage prompt; the architect dispatches it at impl stage. Apply **both** lenses below — they are non-overlapping.

## What B3 ships (orientation)

Five subprocess tools — `run_tests` (rev 9 AUTO), `run_lint`/`git_blame`/`git_log`/`git_diff` (rev 10 AUTO) — run **inline on the single writer**, **before** the P4.3 syscall sandbox, with a lighter posture: allowlisted argv (no `shell=True`), scoped env (`build_scoped_env`), bounded timeout + bounded output, `cwd=sandbox_root`, kill-no-orphan + watchdog, per-turn cap. They ride the **existing Posture-B `LocalToolFn` path** (`_is_posture_b_subprocess=True`; `_execute_local_call` byte-unchanged). New code: `mcp/subprocess_trust.run_scoped_command` + `tools/subprocess_tools.py`; the `snapshot_excerpt` exclusion filter widens to subprocess results. The honest residual: the subprocess is **NOT** syscall-isolated (FS-read + outbound-network within operator perms) — Accepted exactly as ADR-031 D1a `RB-FS/NET`, retired by P4.3.

---

## Lens (a) — Subprocess **trust boundary**

Probe whether the trust boundary is real where claimed and honest where not:

1. **Argv-injection / command-injection.** Is there **any** path to `shell=True`, a shell-string, or `os.system`? Can a tool **param** influence argv beyond the allowlisted `path`/`max_count` — e.g. flag passthrough (`-p`/`--pdb`/`-c`/`--upload-pack`), a path that resolves flag-shaped (starting with `-`), or a git ref? Verify the **resolved absolute path** (not the raw LLM string) is what enters argv, and that git commands use `--`. Confirm the new constitution test (`t9`) actually catches a re-introduced `shell=True`.
2. **Env-scoping (the c2 lesson).** Does the child env ever contain the orchestrator's full `os.environ`, an `api_key`/secret/credential key, or anything beyond `_SAFE_ENV_KEYS`? Is `build_scoped_env` genuinely reused (not a divergent re-implementation)? If a `scoped_env()` core was factored out, did it preserve the existing tested behaviour?
3. **Output-as-untrusted framing + the P4.1-filter extension.** Subprocess stdout is external/untrusted (a malicious commit message via `git_log`, attacker strings via `run_tests`, a crafted `git_diff` hunk). Verify: (i) it is rendered **raw** (exact bytes preserved), **not** interpreted→`OBSERVATION`; (ii) it is **excluded** from `snapshot_excerpt` (the cross-agent system-block surface) — and that the exclusion set stays in sync with the registry (the drift sync-test). **Critically:** confirm the claim that excluding it does **not** blind the acting agent — the raw bytes still reach it via `current_event` (`api/app.py:454`). Can crafted result text in a subprocess `TOOL_RESULT` steer a **re-dispatched** agent through the system block? (The P4.1 Y1 surface, now widened.)
4. **Residual honesty.** Is the `RB-FS/NET`-class residual inscribed as the **real** surface (FS-read + outbound-network within operator perms), not softened? Is it correctly scoped as **narrower** than ADR-031 D1a (first-party fixed-argv over a trusted workspace) and wired to **one** retirement path (P4.3 wraps `run_scoped_command`)? Flag any place the ADR over-claims "isolation"/"sandbox".

## Lens (b) — **Liveness** under the single writer × the turn-loop's N passes

Probe whether the single-writer block stays absolutely bounded when subprocess forks multiply by `(1+N)`:

1. **Kill-no-orphan + watchdog.** A hung `run_tests`/`run_lint` (or a child that forks workers/grandchildren) — is it **process-group** killed (`start_new_session=True` → `pgid==pid`; `_terminate_subprocess` SIGTERM→SIGKILL) and reaped, with the LAYER-1 `_kill_watchdog` backstop? Any orphan / zombie-reap race? Does the timeout path actually unblock the single writer (no shielded coroutine leaking)?
2. **Per-turn cap.** Does `MAX_SUBPROCESS_CALLS_PER_TURN` (renamed from `MAX_POSTURE_B_CALLS_PER_TURN`) bound **all** subprocess forks per turn — plugin Posture-B **and** B3 — with excess → `TOOL_FAILED(turn_subprocess_cap_exceeded)`? Is the cap counted in `execute_pending_tool_calls` (mechanism) and **not** in `_execute_local_call` (empty-decision-diff, t3b)?
3. **Bounded output.** Is stdout/stderr truncated at `MAX_RESULT_BYTES` **as it is read** (so an unbounded test log never buffers fully into the writer)? Confirm an OOM-via-output path is closed.
4. **The compounding term.** The worst-case single-writer block is now `≤ MAX_SUBPROCESS_CALLS_PER_TURN × subprocess_timeout × (1+N) passes` (ADR-028 D5 × ADR-033 D4). Is every term finite and the multiplier inscribed (not accidental)? Is `run_tests`'s timeout high enough to be useful yet bounded enough not to stall every room's writes? Flag any unbounded inline dependency on the subprocess path.

---

**Output:** findings tagged by lens + severity (🔴 blocking / 🟡 should-fix / 🟢 nit), each with file:line evidence and expected-vs-actual. Route nothing yourself — the architect routes (α/β/γ/δ). Land at `docs/process/reviews/P4.2-B3/R0-B.md`.
