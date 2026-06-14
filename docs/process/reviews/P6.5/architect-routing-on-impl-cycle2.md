---
task_id: P6.5
stage: architect-routing-on-impl
cycle: 2
actor: architect (orchestrator, under the P6 bug-fix-backlog delegation)
date: "2026-06-14"
routing: accept-as-shipped
disposition:
  R0B-N1-nonforce-glob: accept-as-shipped-followon   # task #110
inputs:
  - docs/process/reviews/P6.5/plan-vs-impl.md   # cycle-2 clean
  - docs/process/reviews/P6.5/R0-A.md           # cycle-2 clean
  - docs/process/reviews/P6.5/R0-B.md           # cycle-2 needs_architect (1 🟡 N1, non-destructive)
---

# P6.5 cycle-2 routing — accept-as-shipped (merge)

cycle-2 resolved everything that matters: **plan-vs-impl + R0-A clean**; R0-B confirmed the cycle-1
🔴 R1 / 🟡 R2 **refspec-delete/-force bypasses are fixed** (`branch` starting `:`/`+` rejected) and
**empirically re-verified the exhaustive destructive set is blocked** (incl. full-ref deletes, force-glob
`+refs/heads/*`, and the whitespace-prefix bypass hypothesis *falsified* on git 2.43). The security
objective — block delete/force on git_push — is **fully met and cross-family-verified.**

R0-B's lone remaining item is **N1 (🟡, explicitly non-destructive):** a *non-force* glob refspec
`refs/heads/*:refs/heads/*` has no `:`/`+` prefix → passes the guard → git would push *all* branches.
**Accept-as-shipped:** it carries **no destructive payload** (no `+force` ⇒ non-ff rejected; no `--prune`
⇒ no deletion; no `--mirror` ⇒ no tag/non-branch refs), the **force-glob variant IS caught** by the
`+`-prefix check, and git_push is **rev-1 HARD → always human-confirmed** with the `branch` value (incl.
a visually-obvious glob) surfaced in the dialog. The only wart is the guard's error message
("only plain branch names are accepted") slightly over-claiming, since the tool intentionally permits
normal `main:other` / `HEAD:main` pushes.

**Disposition:** merge P6.5 now (the destructive bypasses are closed); record N1 as **task #110** — a tiny
follow-on to reject `*` (glob) in `branch` (keeping plain names + simple `src:dst`) and reword the guard's
error message accurately. Not worth a cycle-3 for a non-destructive, HARD-confirmed edge.

(Routed by the orchestrator under the delegated bug-fix-backlog authority: the destructive-bypass security
fix is complete + verified; N1 is a non-destructive residual deferred to #110. No spine/ADR-contract touch.)
