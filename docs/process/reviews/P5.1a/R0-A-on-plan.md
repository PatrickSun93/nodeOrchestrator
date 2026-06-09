---
task_id: P5.1a
stage: R0-A-on-plan
reviewer: architect-partner
verdict: needs_architect
findings_count: 3
lenses: ["A: pipeline safety + determinism", "B: spine no-regression"]
reviewed:
  - "docs/process/senior-plans/P5.1a.md"
  - "docs/decisions/ADR-041-deterministic-analysis-pipeline.md"
against:
  - "docs/process/architect-briefs/P5.1.md (decision-surface)"
  - "ratification commit f720753"
substrate_verified_at: "main @ d51af80 / HEAD 9027fd9"
date: "2026-06-09"
---

# R0-A-on-plan — P5.1a deterministic analysis pipeline (plan + ADR-041)

**Verdict: `needs_architect`** — the design is sound, exceptionally well-grounded, and
honors the ratified DP1/DP3/DP4/DP5/DP7 leans. Three items need an architect call before
Accept (one scope-boundary, two design-posture), **plus** the one genuine design fork the
senior correctly surfaced (§5 of the plan) which the architect must route before T3.
Nothing is blocking — no substrate claim is wrong, no spine regression is designed in.

## Method

R0-A **on plan** (no code yet). I verified every load-bearing substrate citation in the
plan + ADR against the living code (so the junior builds on real ground), then ran both
ratified lenses against the design. NOT relitigating the ratified DP0-wave/DP1/DP3/DP4/DP5/DP7
— only checking the design honors them.

## Substrate grounding — every cited symbol verified accurate ✅

The plan + ADR are unusually well-cited; I checked the load-bearing references and **all
are accurate**:

| Claim | Verified |
|---|---|
| `_write_and_turn` is HTTP/writer-bound, no headless entry (DP1 foundation) | ✅ nested `def` at `api/app.py:933` inside `_post_intent:880`, returned via `run_in_executor(writer_executor, _write_and_turn)` at `:1044` — no standalone callable |
| The gate `process_tool_calls` + COUNTDOWN/HARD stamp guards | ✅ `tool_dispatch.py:60`; guards at `:130-160` ("HARD_CONFIRM always stays None", stamp iff COUNTDOWN + enabled + reversibility ≥ floor) |
| `execute_pending_tool_calls` + `_execute_local_call` | ✅ `tools/executor.py:82` + `:385` |
| SSRF floor primitives | ✅ `net_trust.py`: `is_denied_ip:48`, `_resolve_and_validate:95`, `build_ssrf_client:194` (redirect re-validation) |
| File sandbox | ✅ `local.py:_check_path:120` (resolve + containment, rejects traversal/symlink/absolute) |
| `EventType.OBSERVATION` / `SUMMARY_SNAPSHOT` exist (T4) | ✅ `core/event.py:83,88` |
| `approval_source: Literal["human","auto_timer"]` (byte-freeze target) | ✅ `core/event.py:224` — byte-exact, no `auto_pipeline` |
| `RoomType.FREE_CHAT` exists (T4 reuse) | ✅ `core/room.py:23` |
| `LLMPurpose.AGENT_RESPONSE` is the content-gen call; all 9 members are content purposes | ✅ `llm/purposes.py:36` |
| `connectors/` = ADR-019 `EXTERNAL_VALIDATION` **output** producers (collision target) | ✅ `dataset_check.py` + `_emit.py` write-only; `pipeline/` + `sources/` confirmed greenfield (no dirs) |
| `MAX_TURN_LOOP_PASSES=4`, `_writer_approve_helper:285`, side-table precedent `users.py`, `ThresholdConfig`, `build_user_author` | ✅ all present as cited |

**The §5 fork is correctly characterized.** I read the turn-loop (`api/app.py:955-1036`)
+ `dispatch_turn` (`dispatch.py:88-166`): the re-dispatch loop calls `dispatch_turn` (which
gates every agent via `should_agent_speak:89` and only then calls `process_tool_calls:153`)
+ `execute_pending_tool_calls`. A pipeline forced-single-agent branch genuinely **cannot**
flow through `should_agent_speak`, so true loop-sharing requires parametrizing dispatch —
exactly the "alternative B refactor" the senior names. The D2 lean (reuse the gate +
executor units verbatim, duplicate ~30 lines of bounded-pass scaffolding, leave
`_write_and_turn` byte-untouched) is faithful and technically sound: the runner builds its
own `LLMRequest(purpose=AGENT_RESPONSE)` → append `UTTERANCE` → `process_tool_calls` (the
same gate `dispatch_turn` calls internally) → `execute_pending_tool_calls`.

## Lens A — pipeline safety + determinism: PASS (with F2/F3)

- **Determinism / no silent partial** — honored. T3 forces the single `agent:pipeline` per
  branch, never `should_agent_speak`/`dispatch_turn`/emergent re-dispatch; "all configured
  sources fetched + all configured prompts run; a single failure is *recorded* (fail-closed
  isolation), not dropped." Recorded-partial ≠ silent-partial — the property the brief wants.
- **Fetch SSRF/sandbox-floored** — honored, and **tested not asserted** (a real strength).
  T1 requires web/rss through the *identical* `_resolve_and_validate` floor (redirect
  re-validates, never bypassed), file through `_check_path` containment + byte bound, and
  §4 forces T1 tests to include a **denied-IP feed URL + a traversal path that are rejected.**
  The RSS/Atom parser — the one greenfield attack surface — is required **XXE/billion-laughs
  safe** (`defusedxml`/entity-disabled) + **malformed-fail-closed.** This is the right catch.
- **No new actuator authorization surface** — honored. T3: any HARD/irreversible tool an
  analyze branch proposes produces a `TOOL_CALL_PENDING` that **waits** — the runner performs
  **no** `_writer_approve_helper` call, no auto-fire. Output (T4) is reversible room append
  (`OBSERVATION`/`SUMMARY_SNAPSHOT`), **not** gate-routed. No email anywhere. Verified the
  design introduces no headless actuation.

## Lens B — spine no-regression: PASS

- Gate (`score`/`decide_tier`/`emit_gate_decision`) + `_execute_local_call` **byte-frozen** —
  reused, never edited; §4 diff-freeze check explicitly halts on any change to gate logic,
  executor core, `_writer_approve_helper`, `approval_source` Literal, EventType + RoomType enums.
- **No new routing `LLMPurpose`** — analyze + reduce reuse `AGENT_RESPONSE` (content-gen);
  orchestration (stage order, fan-out count, source list, output routing) is all code/config.
- **No new background/lifespan task** — T5 runs synchronously on `writer_executor` via
  `run_in_executor` (like `_write_and_turn`); ADR-025 D6 single-writer + reader-liveness
  preserved; the scheduler is correctly deferred to P5.1b.
- **Room/agent contracts (ADR-010/011/012)** — no new RoomType/EventType (T4 reuses
  `FREE_CHAT` + existing events); the runner never dispatches into the room. (See F2 for the
  one honesty nuance.)
- **Shared run path** — T5's `POST /pipelines/{id}/run` and the future scheduler call **one**
  `run_pipeline` (scheduler = second caller, not a second code path). Good seam for P5.1b.

## The open architect decision (route before T3)

**The §5 analyze-branch loop-reuse fork.** The senior correctly surfaced this as the one
genuine design decision and **gated T3 on it** (exactly right — surface, don't decide):
- **D2 lean (ADR-041 D2):** reuse the gate + executor verbatim, duplicate ~30 lines of
  bounded-pass scaffolding, **interactive `_write_and_turn` byte-untouched** (a Lens-B win).
- **Alternative B (ADR-041 Considered-alt B):** extract a shared dispatch-pluggable
  `run_turn_loop` both paths call — the literal "reuse, don't rewrite" reading, **but it
  refactors the interactive spine path** (behavior-preserving extraction still enlarges the
  interactive review surface — a Lens-B hazard).

My read: the D2 lean is the safer Lens-B posture (spine byte-untouched > DRY) and the
duplication is genuinely ~30 trivial lines. But this is the architect's architecture call.
**Route D2 vs B; T3 is blocked on it.**

## Findings

### F1 — `needs_architect` — Scope boundary: definition-persistence (T2) + manual-trigger (T5) land in P5.1a, but the brief/ratification bundled "persistence + manual trigger" into P5.1b

- **Evidence:** Brief DP0(b) line 47 + ratification `f720753` both read **"P5.1b (recurring
  scheduler + persistence + manual trigger + restart re-arm)"** — i.e. *persistence + manual
  trigger textually in P5.1b*. The plan places **T2 (`pipelines`/`pipeline_runs` side table)**
  + **T5 (`POST /pipelines`, `POST /pipelines/{id}/run`)** in **P5.1a**, citing "the
  architect's P5.1a dispatch (scope = items 1–6)" — a *verbal* dispatch not in the written
  record I can verify.
- **Why it matters:** the written ground truth (brief + ratification commit) and the senior's
  cited chat dispatch diverge on the slice boundary. Per "state/written record is ground truth,
  not chat history," I surface rather than bless.
- **Lean (yours to confirm, not mine to decide):** the inclusion is **defensible and likely
  necessary** — the brief's own P5.1a goal is "a *working*, safe headless pipeline," which is
  un-runnable without an entry point (trigger) + a definition to load (persistence); a pipeline
  with neither is dead code. The senior scoped it **tightly**: T2 has **no** `cron`/`interval`/
  `next_fire` columns, T5 has **no** schedule CRUD, and the run path is the same one the P5.1b
  scheduler will reuse. *Schedule* persistence + the *scheduler* + restart-re-arm correctly
  stay in P5.1b.
- **Architect:** confirm definition-persistence + manual-trigger are in-scope for P5.1a (I
  believe they are, per your "working pipeline" goal) — or pull them to P5.1b. *(Not relitigating
  DP0-wave or DP7-side-table — both ratified; only the slice allocation.)*

### F2 — `needs_architect` (low) — The pipeline-run room's non-conversational property is convention, not enforcement

- **Evidence:** ADR-041 D6 states the `FREE_CHAT` pipeline-run room "**never receives
  `/intent`**." But `_post_intent` (`api/app.py:880`) guards only `body.type` against an intent
  allowlist (`:905`) — **no room-type guard.** Any existing room, including a pipeline-run
  `FREE_CHAT` room, remains `/intent`-reachable; a human POST would run `select_dispatch_agents`
  + `should_agent_speak` and emergent agents could speak into it.
- **Why it matters:** the runner-behavior claim ("the runner never dispatches") is true, but the
  ADR slightly overstates it as an *enforced* room property. Consequence is **low** (a normal,
  reversible conversation in a `FREE_CHAT` room after output already landed — no spine/safety/
  authorization impact). But this project inscribes residuals honestly, and an ADR is a contract.
- **Lean:** acceptable for P5.1a **if** D6 inscribes the property as *convention-not-enforcement*
  (the runner doesn't dispatch; the room stays reachable) — the structurally-inert version is the
  already-deferred `PIPELINE` RoomType (D6/D10). A one-line ADR honesty edit, not a rework.

### F3 — `needs_architect` (low) — Access-control posture for `/pipelines*` is unspecified (own-only vs any-authenticated)

- **Evidence:** T5 captures `owner_user_id` from the principal for **attribution** and gates
  routes behind auth middleware (server-derived principal, fail-closed) — but the plan/ADR do
  **not** state whether `GET /pipelines/{id}` + `POST /pipelines/{id}/run` are **owner-private**
  or **any-authenticated** (the existing collaborative-room posture — grep shows existing write
  endpoints stamp the author from the principal with no per-resource ACL / `403`).
- **Why it matters:** P4.5 made this a multi-user system. A pipeline definition is a list of
  URLs/files the server will fetch on run; "any authenticated user can run any pipeline" is
  defensible (SSRF-floored, reversible output) but should be a **conscious** posture, the way
  ADR-039 made attribution explicit. Low risk, real omission.
- **Lean:** specify it. Own-only is the safer default for a new endpoint surface; collaborative-
  like-rooms is defensible if rooms are already shared. Architect's call — just make it explicit
  (one line in the plan/ADR), don't leave it implicit.

## Strengths worth recording

- Exemplary substrate grounding — every line citation checked was accurate; the junior can
  trust the plan's references.
- The RSS/Atom **XXE/billion-laughs + fail-closed** requirement (T1) is exactly the right catch
  for the one greenfield attack surface.
- Security floors are **tested, not asserted** (§4 forces denied-IP + traversal test cases).
- The §4 **diff-freeze checklist** (explicit halt-on-change file list for gate/executor/
  `_writer_approve_helper`/`approval_source`/enums) is a strong Lens-B forcing function.
- One shared `run_pipeline` path (T5) is a clean seam so P5.1b adds a caller, not a parallel
  engine.
- The §5 fork is surfaced + T3-gated, not silently decided — correct senior discipline.

## What the architect does next

1. **Route the §5 fork** — D2 lean (spine byte-untouched; my read) vs alternative B (literal
   loop-share; refactors interactive path). T3 is blocked on it.
2. **F1** — confirm definition-persistence + manual-trigger are in P5.1a, or pull to P5.1b.
3. **F2 / F3** — low: confirm the convention-not-enforcement room honesty (F2) + the access-
   control posture (F3); both are one-line plan/ADR edits, not reworks.
4. **ADR-041 Accept** is the architect's (RC-3 — no self-accept); this review is input to it,
   not a substitute.

Route nothing — this is a surface-only review.
