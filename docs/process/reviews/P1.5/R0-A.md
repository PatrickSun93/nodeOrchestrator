---
task_id: P1.5
round: R0-A
verdict: clean
findings_count:
  red: 0
  yellow: 1
  green: 6
---

# P1.5 R0-A review

| Field | Value |
|---|---|
| Round | R0-A (post-impl, architect-partner) |
| Reviewer | architect-partner (Claude Opus 4.7, 1M context) in primary session |
| Date | 2026-05-27 |
| Artifacts reviewed | 5 impl commits on `claude/P1.5-impl`: `211b003` (P1.5-3), `670acfd` (P1.5-5), `5d21370` (P1.5-6 — **bundles P1.5-4** per plan-vs-impl 🟡#1), `9c1c29f` (P1.5-7), `e4b272b` (P1.5-8). Plus `2ae8ed3` (senior plan-vs-impl), `307a8fa` (R1 fix), `a7ddf4f` (plan-vs-impl verdict bump). +2464 / -67 lines. 677 tests post-impl (was 602 at P1.4 close; +75). |
| Brief lean | R0-A dispatch standard for impl-side (matches P1.4 + W-002 + W-002.5 precedent). |
| Distinct from plan-vs-impl | Senior plan-vs-impl (`2ae8ed3` + verdict bump `a7ddf4f`) covered: 8 task acceptance, all 7 routing items, all 4 constitutional tests, all 6 §-categories, R1 fix correctness, parallelism-rule discipline 🟡. This R0-A focuses on **ADR-012 invariant compliance in code**, **R1 cycle handling through the harness**, **first-parallelism-rule retrospective lessons**, **RC-16 latent-risk status**, **forward implications for P1.5.5**. |

---

## Findings

### 🟢 G1 — ADR-012 invariants land correctly in code

Architect-partner verification of code sites against ADR-012's 7 Decisions:

- **D1 (per-RoomType code-driven event-triggered)**: `src/orchestrator/rooms/state_machine.py:1-8` declares "pure function: no I/O, no LLM, no event_store reads"; `next_room_state` signature at line 134 takes snapshot + current_event by parameter (no global state). ✓
- **D2 (per-RoomType Literal state sets)**: Research has 6 states (`setup → exploration → divergence → convergence → snapshot_pending → closed`); 4 scaffolds with `{setup, closed}`. Per-RoomType dispatch in `next_room_state` body. ✓
- **D3 (`agent.applies_to` with `["*"]` sentinel + default_factory)**: Y1 → β routing absorbed. `Agent.applies_to: AgentAppliesTo` with default_factory (brief lean restored); `_reject_mixed_star` validator present. ✓
- **D4 (two-layer filtering)**: `decide_agents_for_room(room_type, room_state, ...)` regains the params dropped in P1.4 per DeepSeek R0-B 🟡#3; load-time filter on `applies_to.room_types`; dispatch-time `room_states` filter in `RoomRuntime.run_turn`. ✓
- **D5 (separate `RoomRuntime`)**: `src/orchestrator/rooms/runtime.py` standalone module; not inlined into `dispatch_turn`. ✓
- **D6 (`StateTransitionMeta.prior_state`)**: `core/event.py` extended; `RoomRuntime.run_turn:97` populates `prior_state=transition.prior_state` when appending state_transition events. First real producer of state_transition events. ✓
- **D7 (4 layering tests)**: `tests/rooms/test_constitution.py` declares all 4 named tests at lines 24, 82, 95, 108. All green. ✓

**Net**: every load-bearing ADR-012 Decision has a verifiable code site. Zero spec-vs-impl drift.

### 🟢 G2 — Constitutional discipline holds under first-real-room-load

P1.5 is the first task to introduce `src/orchestrator/rooms/`. 4 new constitutional tests load-bearing:
- `test_constitution_no_llm_calls_in_rooms_module` — green
- `test_constitution_core_does_not_import_rooms` — green
- `test_constitution_agents_does_not_import_rooms` — green (reverse direction; wire is rooms→agents)
- `test_constitution_skills_does_not_import_rooms` — green (defensive)

R0-A independent grep verification: `grep -rn "from orchestrator.rooms" src/orchestrator/{core,llm,autonomy,skills,agents}/` returns **zero matches**. No reverse imports introduced. 5-module layering invariant preserved.

`from anthropic` / `from openai` grep in `src/orchestrator/rooms/` returns zero. LLM-free state-machine + runtime; LLM calls flow through `dispatch_turn` → `LLMRouter` per existing protocol.

### 🟢 G3 — R1 fix is correct + cycle-counter behavior holds under first-rework

**First R1 (rework) cycle in project history.** Plan-vs-impl review caught `test_state_transition_event_before_utterance` failing under full-suite due to `get_room_events` unstable secondary ordering. Junior fixed in `307a8fa`: `ORDER BY timestamp ASC, id ASC` → `ORDER BY timestamp ASC, rowid ASC`.

**Why the fix is correct** (architect-partner independent verification): event `id` is a random UUID (`evt_<32-hex>` per `core/event.py`); using it as secondary sort produces non-deterministic ordering when timestamps tie at ms precision. SQLite `rowid` is the implicit B-tree key + insertion-order monotonic (when no explicit INTEGER PRIMARY KEY rebinds it; verified `events` table has no such rebinding). The new ordering is genuinely insertion-order for tied-timestamp events. **Real correctness fix; not a workaround.**

**Cycle-counter behavior**: `.workflow/P1.5.yaml` shows `cycle: 1`. R1 was a fix-on-same-branch (not a `workflow override` of `awaiting_architect_decision → awaiting_junior_impl`); the W-002-2 record_override fix correctly leaves cycle alone for non-rework transitions. **First time the cycle counter behaved correctly under a real R1 cycle** (vs prior P1.3 + W-002 where cycle=2 was the BUG evidence). The fix W-002-2 added has now been validated in production.

Override count history unchanged: still 2 (P1.3 + W-002 — both pre-fix bridges).

### 🟢 G4 — RC-16 latent risk did not bite + senior verdict-bump matches RC-10 protocol

RC-16 (`_read_plan_frontmatter` reads working-tree, not `origin/main`) latent. P1.5 cycle: all state advance happened post-PR-#14-merge (plan + ADR-012 on main); RC-16 risk window didn't open.

Senior's plan-vs-impl verdict bump at `a7ddf4f` (blocking → clean after R1 fix) matches RC-10 codified protocol — **6th project use** of frontmatter-as-live-signal pattern. Pattern is increasingly stable; codification target (`docs/process/reviews/README.md` section) for W-003.

### 🟢 G5 — Parallelism rule first formal use produced partial-discipline retrospective signal

Plan §3 designed P1.5-4 ‖ -5 ‖ -6 as 3 parallel agents (state_machine + selection + templates). Actual commits:
- `211b003` P1.5-3 (sequential gate — as designed)
- `670acfd` P1.5-5 (selection update — independent commit ✓)
- `5d21370` P1.5-6 (templates **+ bundles P1.5-4 state_machine** — TWO atomic tasks in one commit subject; bundling per junior judgment OR parallelism collapse)
- No standalone P1.5-4 commit subject

Senior plan-vs-impl flagged this as 🟡#1 — "commit 5d21370 bundles P1.5-4 under P1.5-6 subject." Carries to retro.

**Architect-partner R0-A independent observation**: the bundling itself is benign (the files are in separate `src/orchestrator/rooms/` modules; the commit just has a wrong subject + the parallelism rule's "1 atomic = 1 commit" implicit constraint was relaxed). But it's a **first-use signal** that the parallelism rule needs codification:

- **Constraint that the rule was missing**: "if N atomic tasks are dispatched in parallel, the result MUST be N commits, each with that atomic's commit subject."
- **Why it matters**: tracking-table composites in landing commits depend on per-atomic commits to map back to plan tasks. P1.5-6's bundling means the P1.5-8 tracking table needs special-case handling for the bundled subject.
- **Severity for P1.5**: low (test_state_machine.py + test_templates.py both present; full coverage holds; only subject discipline broke).
- **Severity for W-003+ codification**: medium (codify the constraint before parallelism rule sees more use; surface as RC-17 candidate).

### 🟢 G6 — Forward implications for P1.5.5

P1.5 closes the room state machine + filtering substrate. P1.5.5 (operator + autonomy-aware tools + divergence_mapper + logger yamls) consumes:

- **`Agent.applies_to` with `["*"]` default_factory**: operator will declare `applies_to: {room_types: ["bug_fix", "research"], room_states: ["debugging", "exploration"]}` (or similar). The default_factory is the safe path; operator opts-out explicitly.
- **`from orchestrator.autonomy import gate` direction**: P1.4 constitutional tests allow `agents → autonomy` direction (verified). P1.5.5 will add this import; new test required.
- **`required_capabilities: [tools]` validation**: P1.4-5 loader already calls `validate_consistency` (per P1.4 R0-A G1 verification); operator with `required_capabilities: [tools]` will exercise the validation for the first time on a real agent.
- **`StateTransitionMeta.prior_state` consumer**: future tooling that wants to render state-machine arcs (P2 UI; P1.6 decision log) reads this field; P1.5 is the first writer + reader, P1.5.5+ inherit.
- **`RoomRuntime.run_turn` extension surface**: operator's tool-dispatch flow may add a sub-step between `dispatch_turn` and event append (autonomy gate evaluation); the function-based `RoomRuntime` lean from ADR-012 D5 means P1.5.5 may extract a class if state grows.

P1.5.5 will be smaller than P1.5 (no new module; extends existing `agents/` + adds 3 yamls; ~3-5 atomic tasks; ~3-5 days).

### 🟡 Y1 — Parallelism-rule commit-subject discipline needs codification (carry forward from senior plan-vs-impl §1 + R0-A G5)

**Where:** plan §3 specified P1.5-4 ‖ P1.5-5 ‖ P1.5-6 as 3 parallel atomics → 3 commits with respective subjects. Actual: `670acfd` P1.5-5 + `5d21370` "P1.5-6 + bundles P1.5-4" = 2 commits.

**What:** the parallelism rule (added to `senior-planner.md` at `2868d83`) directs junior to dispatch parallel agents but does NOT explicitly require "1 atomic = 1 commit subject." Junior bundled P1.5-4 (state_machine) under P1.5-6 (templates) commit subject. Both files are present + tested; coverage is unaffected; only subject discipline broke. Senior plan-vs-impl flagged 🟡#1. Architect-partner R0-A confirms + adds forward-implication.

**Options for resolution:**

- **(α) Status quo + retro capture**: this bundling worked out fine; no immediate fix needed; capture RC-17 for retro graduation when parallelism rule sees more use.
- **(β) Senior-planner.md amendment**: add a clause to the parallelism rule: "Each parallel atomic produces exactly one commit; commit subject names the atomic id." ~3-5 line addition. Architect-partner direct on main per trivial-fix routing.
- **(γ) W-003 brief absorption**: bundle the codification into W-003 alongside other process-doc refinements (RC-10 verdict-bump codification, RC-16 working-tree-read fix, RC-15 dual-lens-R0-B narrowing).

**My lean: (β)** — the rule is small, the constraint is unambiguous, and codifying now prevents future drift on a pattern that just had its first use. Cost: ~5 lines of `senior-planner.md`. Saves W-003 brief from absorbing a tiny process tweak.

**Severity 🟡**: not a runtime bug; not a code-correctness issue; documentation/discipline question for future parallelism uses.

---

## Cross-checks

- [x] All 677 tests green; ruff/format/mypy strict clean across 100 source files.
- [x] 4 new constitutional tests load-bearing (`grep`-verified zero LLM imports in rooms/; zero reverse imports).
- [x] ADR-012 D1-D7 all verified at code sites.
- [x] R1 fix is correct (rowid is genuinely SQLite insertion-order; not a workaround).
- [x] Cycle stayed at 1 throughout (W-002-2 record_override fix validated for non-rework R1 cycles).
- [x] Senior plan-vs-impl verdict bump at `a7ddf4f` (blocking → clean) matches RC-10 protocol (6th project use).
- [x] RC-16 latent risk did not bite (advance runs post-merge).
- [x] State file currently at `awaiting_senior_plan_vs_impl, cycle: 1` — ready for advance after this R0-A.
- [ ] Y1 above — parallelism-rule commit-subject discipline; architect-partner lean (β) senior-planner.md amendment.

---

## Net assessment

**Verdict: clean.** Six 🟢 + one 🟡 (parallelism-rule codification, not P1.5 impl issue).

P1.5 is the second end-to-end clean cycle through impl (after P1.4) AND the first cycle to validate post-fix harness behavior under real pressure:
- **First R1 cycle in project history**; cycle counter stayed at 1 (W-002-2 fix validated).
- **First parallelism-rule use**; mostly worked (Y1 commit-subject discipline gap; codifiable).
- **First state_transition event producer + StateTransitionMeta.prior_state consumer** (P1.4 added the schema; P1.5 is the first real use; both populate correctly).
- **First single-ADR-string Accept post-W-002.5 union extension** (verifies the str discriminator path didn't regress when list-path landed).

**Recommendation: state machine auto-trigger chain (`awaiting_senior_plan_vs_impl → awaiting_R0_A → awaiting_PR_merge`) fires on next `workflow advance --task-id P1.5`.** Three-advance close shape matching W-002 + W-002.5 + P1.4. PR merge → final `closed` advance.

## Captured for P1.5 retro

- **First R1 cycle**: harness behaved correctly (cycle=1 preserved; W-002-2 fix in real use). Pattern established for handling "review found bug; junior fixes on same branch; verdict bumps; no override needed."
- **First parallelism-rule use**: 2-of-3 commits matched plan; 1 bundled. Codify the "1 atomic = 1 commit subject" constraint in `senior-planner.md` (Y1 lean β) — RC-17 candidate.
- **Senior verdict-bump pattern stable**: 6 uses of RC-10 protocol. Codification ready for W-003.
- **Architect substrate compression**: P1.5 cycle from plan-publish-on-main to impl-done was <1 day. Substrate test honored at ADR-012 Accept (architect chose push-through with explicit retro capture). Captured for P1.5 retro as RC-8 substrate-override observation #1 post-codification.
