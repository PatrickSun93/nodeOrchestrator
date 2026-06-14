---
task_id: P6.5
stage: architect-routing-on-impl
cycle: 1
actor: architect (orchestrator, under the P6 bug-fix-backlog delegation — 2026-06-11)
date: "2026-06-14"
routing: alpha-bundle
disposition:
  R0B-R1-refspec-delete: alpha       # 🔴 — fix (real destructive-op bypass)
  R0B-R2-refspec-force: alpha        # 🟡 same blind spot
  R0A-Y1-vacuous-tests: alpha        # test-honesty
  R0A-Y2-ext-false-pass: alpha
  R0A-Y3-annotation-wording: alpha   # one-word tweak + apply_edit caveat
  R0A-Y3-apply_edit-followon: defer  # task #109
inputs:
  - docs/process/reviews/P6.5/plan-vs-impl.md   # senior, clean
  - docs/process/reviews/P6.5/R0-A.md           # arch-partner, needs_architect (Y1/Y2/Y3, test-honesty)
  - docs/process/reviews/P6.5/R0-B.md           # r0b cross-family, BLOCKING (R1 refspec bypass)
---

# P6.5 impl-stage routing — α bundle, one rework cycle (cycle 2)

G1 (transport allowlist + configured-remote restriction) is correct + safe on the security axis (plan-vs-impl clean; R0-A confirms the impl is right). Two review threads to absorb, **all routine git_push input-validation hardening / test-honesty — no contract change, no spine touch**:

| # | Sev | Source | Fix |
|---|---|---|---|
| **R0B-R1** refspec-delete | 🔴 | r0b (cross-family) | `branch=":main"` deletes the remote ref, evading the `--delete` exact-match ban (empirically confirmed git 2.43 — "deleted main"). **Fix:** before argv build, reject a `branch` value starting with `:` (deletion refspec) **or** `+` (force-push refspec) → `LocalToolError` "only plain branch names accepted". Same git_push tool + same exfil/destructive lens G1 hardens; surgical input-validation, no contract change. |
| **R0B-R2** refspec-force | 🟡 | r0b | `branch="+main:main"` = non-fast-forward force-push, evades the `--force` ban. **Same fix** as R1 (the `:`/`+` prefix reject covers both). |
| **R0A-Y1** vacuous tests | 🟡 | R0-A | The happy-path test passes even on a *failed* push, and the load-bearing `file`-in-allowlist choice is unguarded. **Fix:** make the happy-path test assert a *successful* push (fail-on-revert), + add a regression test pinning the transport-allowlist set (incl. the `file`/`ext` exclusion). For a security slice the guard must bite (Q5). |
| **R0A-Y2** ext false-pass | 🟡 | R0-A | The `ext::` defense-in-depth test is a false-pass. **Fix:** make it assert the actual rejection (not a path that passes regardless). |
| **R0A-Y3** annotation | 🟡 | R0-A | ADR-036 D3-iii note says "operator-configured remotes" — slightly optimistic (an in-sandbox `apply_edit` could add a remote to `.git/config`). **Fix (wording):** "configured remotes" + a one-line apply_edit caveat. The underlying config-poisoning follow-on → **task #109** (deferred, out of P6.5 scope — a different vector; git_push is rev-1 HARD/human-confirmed + egress proxy is the hard boundary). |

cycle-2 = R1/R2 refspec reject (+ tests) + Y1/Y2 test-honesty fixes + Y3 wording, all on `claude/P6.5-impl`. No spine change, no new `LLMPurpose`, no isolation-contract change (ADR-037 D2 untouched); the refspec reject is the same ADR-036 D3-iii input-validation surface as G1. fail-on-revert for the refspec tests (`:main` ⇒ `LocalToolError` + remote ref intact; `+main:main` ⇒ rejected; `main` ⇒ works). After cycle-2 clears → merge → P6.5 closes.

(Routed by the orchestrator under the delegated bug-fix-backlog authority: all items are git_push input-validation hardening + test-honesty, no spine/ADR-contract/residual touch. R0-B's R1 is a genuine security catch — same cross-family lens that caught P6.1 Bug B — and is fixed, not deferred.)
