---
task_id: P6.5
kind: plan-vs-impl
author: senior
surface: product
plan: docs/process/senior-plans/P6.5.md
routing: docs/process/reviews/P6.5/architect-routing-on-impl.md
plan_has_adr: false
cycle: 2
reviewed_commit: 3ae8042
reviewed_branch: origin/claude/P6.5-impl
requires_cross_family_review: true
verdict: clean
---

# P6.5 — senior plan-vs-impl (cycle 2: α rework — refspec reject + test-honesty)

Reviewed `origin/claude/P6.5-impl @ 3ae8042` (cycle-2 rework, single commit `P6.5 cycle-2 α rework: refspec bypass fix + test-honesty fixes`) from `main` via `git diff 88ac9bd..origin/claude/P6.5-impl`. This **supersedes the cycle-1 verdict** (was `clean @ fb68efc`). Cycle 1 verified the G1 core against `docs/process/senior-plans/P6.5.md`; cycle 2 verifies the rework against the architect routing call (`architect-routing-on-impl.md`, α bundle), which dispatched five fixes from R0-A (Y1/Y2/Y3) + R0-B (R1/R2). The cycle-1 G1 core (configured-remote restriction + `GIT_ALLOW_PROTOCOL` transport allowlist on both paths) is **unchanged** by this diff and remains faithful — I re-confirmed the name-check (`"not a configured remote"`, `:462`) is still present.

**Verdict: clean.** Every α-routed item is implemented faithfully to the routing disposition; the one deferred item (Y3 apply_edit config-poisoning follow-on → task #109) is correctly left untouched. Zero plan-external expansion: the rework touches exactly the three files the routing implies (`subprocess_tools.py` +5 lines, `test_subprocess_tools.py`, `ADR-036`), with no spine diff, no new `LLMPurpose`, no isolation-contract change, no `.workflow/` commit on the branch. Gates (ruff/mypy/pytest, t9/t12) are the R0-A/R0-B re-review lens per the dual-lens dispatch — not re-run here.

## Routing-faithfulness — α dispositions

| Routed item | Sev | Disposition | Impl | Faithful |
|---|---|---|---|---|
| **R0B-R1** refspec-delete | 🔴 | α | `subprocess_tools.py:416-421`: `if branch.startswith(":") or branch.startswith("+"): raise LocalToolError("…only plain branch names are accepted")` | ✓ |
| **R0B-R2** refspec-force | 🟡 | α | same guard (`+` covered by the same `startswith` check) | ✓ |
| **R0A-Y1** vacuous tests | 🟡 | α | happy-path `git init -b main` + `assert "exit_code=0"` (was `"exit_code="`); new `test_git_push_transport_allowlist_set` pins the allowlist set | ✓ |
| **R0A-Y2** ext false-pass | 🟡 | α | ext test asserts `"not allowed" in result.content` (was `"exit_code="`), keeps `not pwned.exists()` | ✓ |
| **R0A-Y3** annotation wording | 🟡 | α | ADR-036 D3-iii: "operator-configured" → "configured" + apply_edit/`.git/config` caveat + task #109 | ✓ |
| **R0A-Y3** apply_edit follow-on | — | defer (#109) | no in-cycle stab; named as follow-on only | ✓ (correctly untouched) |

### R1/R2 — refspec reject (the 🔴, the load-bearing fix)

- **Placement guards both dispatch paths.** The new guard sits at `:416-421`, **after** the flag-shape check (`branch.startswith("-")`, `:411`) and **before** the argv build (`:425`) and the `if posture_resolver is not None:` branch (`:432`). So it rejects `:`/`+` refspecs on the non-sandbox `_dispatch` path too — same "guards the RCE/destructive path before any push" structure the cycle-1 configured-remote check used. This matches R0-B's suggested fix direction ("a third input-validation rule before the argv is built") exactly.
- **Both destructive spellings covered.** `":main".startswith(":")` → rejected (deletion); `"+main:main".startswith("+")` → rejected (force-push). Closes the two refspec syntaxes that bypassed the literal `--delete`/`--force` ban + the `-`-prefix check.
- **Fail-on-revert tests.** `test_git_push_refspec_delete_rejected` builds a real bare+src, pushes `main`, then asserts `:main` raises `LocalToolError` (match `"only plain branch names are accepted"`) **and** `git ls-remote` proves the remote `main` ref still exists — a genuine fail-on-revert (revert the guard → the ref is deleted → `ls.stdout` empty → test fails). `test_git_push_refspec_force_push_rejected` asserts `+main:main` rejection. Both match the routing's literal fail-on-revert spec (`:main ⇒ LocalToolError + remote ref intact`; `+main:main ⇒ rejected`).

### Y1 — happy-path no longer vacuous + `file`-allowlist now guarded

R0-A's Y1 had two prongs; both are closed. (i) The happy-path test now seeds `git init -b main` so the default branch matches `branch="main"`, and asserts `"exit_code=0"` with a diagnostic message — a failed push (the prior false-pass) now fails the test. Because the bare remote is a local path, this push exercises the **`file` transport for real**, so dropping `file` from `_GIT_ALLOW_PROTOCOL` would make it fail. (ii) `test_git_push_transport_allowlist_set` independently pins the set: asserts `https`/`ssh`/`git`/`file` present and `ext` absent — the explicit regression guard on the senior §5(a) load-bearing choice the routing asked for. The `file` decision is now doubly guarded (behavioural + set-membership).

### Y2 — ext test now bites

`test_git_push_ext_protocol_blocked_by_allowlist` asserts `"not allowed" in result.content` (git's `fatal: transport 'ext' not allowed`) instead of the always-true `"exit_code="`. This is exactly R0-A's suggested strengthening: without the allowlist the error is "Bad command" (the `ext::` space-split artefact R0-A diagnosed), not "not allowed" — so the assertion now fails-on-revert of `_GIT_ALLOW_PROTOCOL`. The load-bearing `not pwned.exists()` assertion is preserved.

### Y3 — annotation precision + correct deferral

ADR-036 D3-iii annotation reworded from "NARROWED to **operator-configured** remotes" to "NARROWED to **configured** remotes" and gains the caveat "an in-sandbox `apply_edit` can extend `.git/config` — config-poisoning follow-on task #109". This is the honest narrowing R0-A asked for (the name-check trusts `git remote`, which an in-sandbox `apply_edit` under repo-root can extend via `.git/config`). The underlying follow-on is **deferred to task #109** — no in-cycle stab at `.git/`-deny or remote-source hardening, faithful to the routing's `defer` disposition and to architect-deferral literal-reading discipline (no opportunistic "defensive hardening" bundled under the deferral).

## Plan-implied invariants — no drift

- **Layered defence intact.** Cycle-2 adds a third input-validation rule (refspec reject) ahead of the cycle-1 layers (configured-name restriction + `GIT_ALLOW_PROTOCOL`). All three are param-boundary / transport checks before argv build; none touches `_resolve_git_remote_host` parse logic, `_sandbox_dispatch`, or the ADR-037 D2 egress-pinning contract.
- **Argv discipline preserved (t9/t12 by inspection).** argv stays fixed `["git", "push", remote, branch]` (`:425`); the new guard only *rejects* inputs, never reshapes argv. No shell, no new flag surface. No new `LLMPurpose` (tools/ covered). The full gate is the R0-A/R0-B re-review surface.
- **Scope is exactly the routing.** No plan-external functional files, no spine diff. The branch's `.workflow/P6.5.yaml` lag vs `main` is `main` moving ahead (orchestrator state advances), not a junior state-advance commit — no commit on the branch touches it.

## State

Per ADR-008 Amendment 1 (W-005, Route B): state auto-advances `awaiting_senior_plan_vs_impl → awaiting_R0_A` on this clean verdict. `requires_cross_family_review: true` → cycle-2 re-runs the full impl-stage dual-lens (R0-A + R0-B) on `3ae8042`, subprocess-injection threat-probe lens — re-verifying the refspec reject (the 🔴) and the test-honesty fixes empirically + gate-green. No architect decision is open at this stage: all routing calls were the architect's (α bundle / #109 defer); this review confirms faithful absorption only.
