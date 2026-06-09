---
task_id: P5.1a
stage: architect-routing-on-impl
cycle: 1
actor: architect
date: "2026-06-09"
routing: all-alpha
disposition:
  B1: alpha
  F-runid: alpha
  F-deadloop: alpha
  F-succeeded: alpha
  F-ownerparam: alpha
rework_to: junior (cycle 2)
inputs:
  - docs/process/reviews/P5.1a/plan-vs-impl.md   # senior, needs_architect (Y1 RSS-XXE, Y2 dual run_id)
  - docs/process/reviews/P5.1a/R0-A.md           # arch-partner, needs_architect (B1 🔴 + Y1 dead loop + Y2 succeeded)
  - docs/process/reviews/P5.1a/R0-B.md           # r0b cross-family, needs_architect (F1 run_id + F2 owner param + F3 doc)
---

# P5.1a impl-stage routing — **all-α, one rework cycle**

Three impl-stage reviews returned `needs_architect`; the constitutional spine and
the entire Lens-B no-regression contract are **clean** and independently
gate-green (R0-A + R0-B each ran an isolated detached worktree: ruff + mypy strict
+ full pytest with +61 new tests). Routing is **α on every finding** — one junior
rework cycle (cycle 2). No ADR-041 amendment and no senior plan revision: F-deadloop=α
**restores** the D2 multi-pass behaviour as already written, so the ADR/plan stand.

## Dual-lens note (why B1 is a hard stop)

R0-A **empirically reproduced** a billion-laughs evasion (Py 3.12.3): a prolog
comment pads `<!DOCTYPE` past the 8192-byte `_check_no_entity_declarations` scan
window, after which `ET.fromstring` expands internal entities. Running on the
single `writer_executor` this is a **whole-orchestrator DoS** reachable from any
third-party-controlled feed. R0-B's N7 marked XXE ✅ (took the byte-scan + the
DOCTYPE-at-start tests at face value) — it **missed** the evasion. This is exactly
the cross-family divergence dual-lens exists to catch: **weight R0-A's reproduced
exploit.** B1 blocks Accept.

## Per-finding disposition

| # | Sev | Source(s) | Routing | Fix |
|---|---|---|---|---|
| **B1** | 🔴 | R0-A (pvi-Y1 + R0B-F3 corroborate the doc error) | **α** | Replace the hand-rolled byte-scan with `defusedxml` (`forbid_dtd=True`) per ADR-041 D4's own recommendation — position-independent, closes the padded-prolog evasion. Add a test covering the **comment-padded prolog** payload (current tests only cover DOCTYPE-at-start → false assurance). Make `docs/architecture/sources-vs-connectors.md` describe the **actual** mechanism (defusedxml), removing the nonexistent `_SafeXMLParser` claim. |
| F-runid | 🟡 | pvi-Y2 + R0B-F1 | **α** | Single run_id across the runner↔store boundary: have `run_pipeline` accept a caller-supplied `run_id` (or have the endpoint return the runner's id) so the room-anchor event id == the `pipeline_runs` row id. Test the correlation. |
| F-deadloop | 🟡 | R0A-Y1 | **α** | One-line fix `prev_pass_cursor = prev_cursor` (mirror the interactive `_write_and_turn` loop) so analyze branches can re-dispatch on result events, bounded by the ADR-033 caps — **restores ADR-041 D2 as written**. Add a multi-pass analyze test. |
| F-succeeded | 🟡 | R0A-Y2 | **α** | Make `succeeded` reflect reality (e.g. `branches_succeeded > 0`, or write a `running` row first then update to terminal) so `pipeline_runs.status` distinguishes success from total failure. Cover the all-fail path. |
| F-ownerparam | 🟡 | R0B-F2 | **α** | Stop `run_pipeline(owner_user_id)` being a dead parameter — use it inside the runner (attribute the run / anchor event) so P5.1b's scheduler caller gets consistent attribution. |

## Process note (not a finding)

R0-B committed its review as `R0-B-cross-family.md` onto the **impl branch**
(`origin/claude/P5.1a-impl` @ daf736b) instead of main. Orchestrator copied it to
main under the canonical basename `R0-B.md`. The stray copy on the impl branch is
to be `git rm`'d as part of the cycle-2 rework commit so it does not double-land at
merge.

Senior did not self-accept (RC-3); architect routed (no role re-routed a finding).
