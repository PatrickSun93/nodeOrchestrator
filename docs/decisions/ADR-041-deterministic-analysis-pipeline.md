# ADR-041: Deterministic staged analysis pipeline (P5.1a primitive)

**Status:** Accepted (architect, 2026-06-09) — plan-stage dual-lens cleared (R0-A-on-plan 0🔴3🟡 + R0-B-on-plan cross-family clean/4🟡-precision); architect routed §5 fork = D2 (analyze-branch duplicates ~30 lines, interactive `_write_and_turn` byte-untouched), F1 = T2 definition-persistence + T5 manual-trigger in-scope for P5.1a, F3 = owner-only `/pipelines*` access, and F2/N1 + R0-B Y1–Y4 absorbed (α). RC-3: senior did **not** self-accept. Originally Proposed 2026-06-08.
**Scope:** The deterministic, staged, headless **pipeline primitive** introduced by
P5.1a: the `fetch → fan-out(analyze×N) → reduce` stage-runner, its execution model
over the existing agent-turn substrate, the multi-source read abstraction
(`sources/`), per-branch dynamic prompts as config data, **reversible-only** output
(room/GUI summary), the **manual** run trigger, and pipeline-**definition**
persistence. This ADR governs **P5.1a only**. The recurring **scheduler** + restart
re-arm (P5.1b) and the **headless email actuator authorization** /
`RB-PIPELINE-EMAIL` crossing (P5.1c) are **explicitly deferred** and will extend or
amend this ADR (or land as ADR-042/043); see §"Decisions / 10".

## Context

P5 begins the orchestrator's first **deterministic, staged, unattended** product
capability. The substrate built across P4 is rich — a bounded agent-turn loop
(ADR-033), a runtime tool-executor (ADR-028), the autonomy gate
(`score`/`decide_tier`/`emit_gate_decision`), SSRF-floored network reads (ADR-035/037),
a path-sandboxed file reader (ADR-028 D3), an append-only event store (ADR-001),
the auth/identity model (ADR-039), and (P4.6/ADR-040) the first durable
timed-execution surface + first human-out-of-loop posture (`RB-AUTOFIRE`). P5.1
**reuses heavily** but must add the deterministic, headless spine the conversational
engine never needed.

The **core tension** (architect brief `docs/process/architect-briefs/P5.1.md`): the
orchestrator today is **conversational + emergent + human-driven** — a turn runs only
via `_write_and_turn`, a nested function inside `POST /…/intent`, on the single writer
(`writer_executor`, `max_workers=1`); the agent *set* per turn is decided emergently by
`should_agent_speak` (pure code, ADR-010); every irreversible actuator (`send_email`,
reversibility=3 → HARD_CONFIRM) is human-confirmed. A pipeline is the opposite:
**deterministic** (fixed stage order, explicit fan-out + reduce), **headless** (no
human at run time), and ultimately wants to **actuate an external irreversible output
unattended**. The architect ratified (commit `f720753`) decomposing P5.1 into a
**wave**: P5.1a (this ADR) ships a *working, safe* headless pipeline with **reversible
output only** and **zero new authorization surface**; P5.1b adds the scheduler +
schedule persistence; P5.1c isolates the headless-email crossing for its own dual-lens.

**The framing that keeps P5.1a constitutional.** P4's spine held byte-frozen across all
8 slices: `_execute_local_call` + the autonomy gate zero-diff, **no new `LLMPurpose`
beyond content-gen**. P5.1a holds the same line: **the pipeline's orchestration — stage
order, fan-out count, source list, output routing — is all CODE/CONFIG, never an LLM
judgment** (CLAUDE.md "Never LLM-judge a routing decision"). The **only** LLM in the
pipeline is the **analyze + reduce content-gen** (generate analysis/summary text from
fetched data — `AGENT_RESPONSE`-class). The pipeline **stages, never emerges**.

**What the foundation must support:**
1. Deterministic, fully-executed stages (every configured source read, every configured
   analysis run — no silent partial, no LLM choosing *what* to read or *which* analyses
   to run).
2. Reuse of the proven, gate-correct execution primitives (the gate + the executor),
   **without** inheriting the conversational non-determinisms (`should_agent_speak`,
   result-driven re-dispatch) and **without** regressing the interactive spine.
3. SSRF/sandbox security floors applied to **every** source read, including
   user-suppliable feed URLs.
4. **Zero** new authorization surface: reversible output only; no headless actuation of
   any HARD/irreversible pending; the gate, `_execute_local_call`,
   `_writer_approve_helper`, and the `RB-AUTOFIRE` exclusions all byte-intact.
5. Durable pipeline **definitions** (mutable operational config) + run history, with an
   audit owner, recoverable across restart — without committing the schedule machinery
   (P5.1b) yet.
6. A clean extension seam for P5.1b (scheduler) and P5.1c (headless email) so this ADR
   is **inscribed before** its later producers extend it.

## Decisions

### 1. A deterministic pipeline primitive — independent stage-runner over the agent-turn substrate

P5.1a adds a new package `src/orchestrator/pipeline/` implementing a deterministic
`StageGraph`: **fetch → fan-out(analyze × N) → reduce**. It runs on the existing single
writer (`writer_executor`); every event append serializes there (ADR-028 D1 preserved).
It **reuses** the lower-level units — the autonomy gate (`process_tool_calls`,
`agents/tool_dispatch.py`), the runtime executor (`execute_pending_tool_calls`,
`tools/executor.py`), the SSRF/sandbox read primitives (Decision 4), and the event
store — but **does NOT use the emergent room dispatch**: no `should_agent_speak`, no
result-driven re-dispatch of an arbitrary agent set. Its events land in a room
(Decision 7) so the GUI sees them live.

**Why.** This is the only option that delivers *real* stage determinism (explicit
stages, explicit fan-out, explicit reduce) without bending the conversational contracts
(ADR-010/011/012) into a shape they were designed *not* to take. Riding the room/event
model (the rejected alternative A) would require configuring the conversational engine
to *not* be conversational — single-agent rooms, trigger hacks, fan-out faked as
sequential turns — polluting the room/agent contracts with a non-conversational special
case. An independent stage-runner reuses ~80% of the execution code (gate + executor +
read primitives + store) without inheriting the conversational semantics.

### 2. The analyze branch reuses the gate + executor; the interactive spine is byte-untouched

Each fan-out **analyze branch** = one **bounded agent-turn** for a single ephemeral
agent: construct an `LLMRequest(purpose=AGENT_RESPONSE, …)` (Decision 5) with the
supplied prompt as system text + the fetched data as context; call `llm_router.call`;
append the resulting `UTTERANCE`; route any proposed tool calls through the **existing**
gate (`process_tool_calls`) and execute AUTO_EXECUTE results through the **existing**
executor (`execute_pending_tool_calls`); re-dispatch on result events, **bounded** by
the same caps ADR-033 uses (`MAX_TURN_LOOP_PASSES`, the re-dispatch wall-clock). The
ephemeral analyze identity is `agent:pipeline` (Decision 6 of ADR-039 author scheme),
with **default/conservative autonomy thresholds**, so any tool it proposes is gated
exactly as a normal agent's would be — a HARD call (e.g. `send_email`) produces a
`TOOL_CALL_PENDING` that simply **waits** (no headless actuation in P5.1a; Decision 5).

**The gate and the executor — the constitution-critical logic — are reused verbatim;
they are not re-derived.** The branch driver's only new code is the **bounded-pass
scaffolding** (a for-loop with a cursor + wall-clock check) wrapping a *forced
single-agent* dispatch. This scaffolding is **deliberately NOT shared** with the
interactive `_write_and_turn` (`api/app.py:933-1044`): P5.1a does **not** refactor the
interactive intent handler, keeping the interactive spine path byte-untouched (a Lens-B
priority). The honest residual: ~30 lines of bounded-pass control flow are duplicated
rather than extracted-and-shared, in exchange for zero risk to the interactive turn.

**Routed (architect, 2026-06-09): D2 is the decision** — reuse the gate + executor
verbatim + duplicate the ~30-line bounded-pass scaffolding; the interactive
`_write_and_turn` stays byte-untouched. The "extract a shared, dispatch-pluggable
`run_turn_loop` helper" reading (Considered alternatives B) is **rejected** — Lens-B
(spine byte-untouched) outweighs the DRY win, because the duplicated scaffolding is ~30
lines of trivial control flow whereas alternative B refactors the interactive turn-loop
(a behavior-preserving extraction still enlarges the interactive path's review surface).
T3 implements D2; it is no longer blocked.

### 3. Fan-out is sequential and write-serialized in P5.1a

The N analyze branches run **sequentially** on the writer. The single-writer invariant
(ADR-028 D1) means every event append serializes regardless; P5.1a does not attempt
concurrent LLM calls. **Honest residual:** fan-out is *logically parallel* but executed
*write-serialized*, and P5.1a additionally runs branches *sequentially* (no overlapped
LLM calls) for simplicity. LLM-overlap (concurrent LLM calls with serialized appends) is
a deferred perf optimization (P5.1b+). A manual pipeline run therefore occupies the
single writer for its duration, bounded by `N × per-branch-turn-loop-wall-clock` — the
same property a long interactive turn has. P5.1b may revisit background execution
alongside the scheduler.

A manual pipeline run and the COUNTDOWN sweeper's `_writer_approve_helper` both run on
the **same** `writer_executor` (`max_workers=1`), so they **serialize** — there is no
concurrent write. A sweeper firing while a run is in progress simply queues behind it;
the single-writer invariant is preserved (and, per Decision 5, the run stamps no
`expires_at` on its pendings, so the sweeper has nothing of the pipeline's to auto-fire).

### 4. Deterministic multi-source read — a thin `sources/` abstraction (NOT `connectors/`)

P5.1a adds `src/orchestrator/sources/`: a typed `Source{kind: web|rss|file, locator,
options}` and a per-kind reader dispatched **deterministically** by the fetch stage
(the configured source list is read every run; **no LLM chooses what to fetch**).
- **web** → reuse the SSRF-validating client (`build_ssrf_client` /
  `_resolve_and_validate`, `tools/net_trust.py`): scheme allowlist, IP denylist,
  resolve-then-pin DNS-rebind defense, redirect re-validation, bounded size (ADR-035/037).
- **rss** → reuse the **same** SSRF client + a **new RSS/Atom parser** (the one
  substantive greenfield piece). A feed URL is attacker-influenceable when user-supplied,
  so it flows through the **identical** SSRF floor as a web URL — never a bypass.
- **file** → reuse the path-sandbox read primitive (`_check_path` + bounded read,
  `tools/local.py`): reject traversal/symlink-escape, bounded read.

**Name-collision guard:** the abstraction MUST NOT live in `connectors/` — that
directory is ADR-019 external-ground-truth **output** producers (write-only,
`EXTERNAL_VALIDATION` events), the opposite direction of a read-source. Use `sources/`.

**Deferred:** generic-API-poll beyond plain HTTP (auth headers, GraphQL) and
incremental **last-seen feed state** are out of P5.1a — each run reads the full current
feed; incrementality lands with the scheduler (P5.1b) where "what changed since last
run" first becomes meaningful.

### 5. Dynamic per-branch prompts are config DATA; output is reversible-only

The pipeline definition (Decision 8) carries an **ordered `analysis_prompts: list[str]`**.
Each fan-out branch runs its ephemeral agent-turn (Decision 2) with the supplied prompt
as task/system text + the fetched data as context. **Prompts are config data, injected
at dispatch — not an LLM judgment.** The analyze call and the reduce call both reuse the
**existing `LLMPurpose.AGENT_RESPONSE`** (content-gen) — **no new routing `LLMPurpose`**.

The **reduce** step combines the N branch outputs into one summary (a content-gen
`AGENT_RESPONSE` call over the branch outputs) and appends it to the pipeline-run room
(Decision 7) as a **`SUMMARY_SNAPSHOT`** event (free-form `OBSERVATION` is the
fallback if the reduce is unstructured). This output is **internal, reversible, and NOT
autonomy-gated** — it fires headless freely, the safe-by-default output.

**P5.1a adds ZERO new authorization surface and NO email.** If an analyze branch's
agent proposes a HARD/irreversible tool, the gate produces a `TOOL_CALL_PENDING` that
**waits** for a human `POST /confirm` exactly as today — there is **no headless
actuation** of any pending in P5.1a. `_execute_local_call` and the gate
(`score`/`decide_tier`/`emit_gate_decision`) are **byte-frozen**; `_writer_approve_helper`
and its `approval_source: Literal["human", "auto_timer"]` are **unchanged** (the
`auto_pipeline` marker + the headless-email actuator are P5.1c). The `RB-AUTOFIRE`
exclusions (HARD-never, reversibility-floor) remain byte-intact.

**The mechanism that guarantees "no headless actuation" (the load-bearing detail).** The
runner calls `process_tool_calls` with **`countdown_auto_fire=None`** — so no
`TOOL_CALL_PENDING` the pipeline produces is ever stamped with `expires_at`
(`agents/tool_dispatch.py:133-145` stamps iff `countdown_auto_fire is not None and
.enabled`), and the COUNTDOWN sweeper's `_discover_expired_pendings` (which requires
`expires_at is not None`) therefore **cannot** find a pipeline pending to auto-fire. The
`agent:pipeline` identity uses **conservative, explicit `ThresholdConfig` values**
(`threshold_auto=8, threshold_confirm=5` — all three fields are required; there is no
code-level default), so the AUTO_EXECUTE set is confined to high-reversibility read-only
tools and any lower-reversibility op is gated to a *waiting* pending, never auto-run.

### 6. The pipeline-run room reuses an existing RoomType (no new RoomType in P5.1a)

The pipeline creates an **ordinary room** (an existing neutral `RoomType` —
`FREE_CHAT`) and appends its events there for GUI visibility. It **never** runs
`dispatch_turn` / `should_agent_speak` on that room, so **no conversational agent
emerges** from the pipeline. Consequently the room/agent contracts (ADR-010/011/012) are
**byte-untouched**.

**Honesty: this is a *convention*, not an enforced room property** (R0-A F2 / R0-B N1).
`_post_intent` (`api/app.py:880`) guards `body.type` against the intent allowlist but has
**no room-type guard**, so a `FREE_CHAT` pipeline-run room remains `/intent`-reachable —
a deliberate human (or a bug) POSTing `/intent` to it would run the normal conversational
turn and emergent agents could speak into it. The consequence is **low** (a reversible
conversation in a room after its summary already landed — no spine / safety /
authorization impact). The *structurally-inert* version — a dedicated `PIPELINE` RoomType
that disallows `/intent` — is the deferred option (Decision 10), kept out of P5.1a to
keep ADR-012's state machine untouched. P5.1a inscribes the property honestly as
"the runner does not dispatch; the room stays reachable," not as an enforced invariant.

A **dedicated `PIPELINE` RoomType** (clearer GUI audit, a non-conversational state set)
is **deferred** — it would amend ADR-012's state machine and is outside P5.1a's
amendment set. It can land when the GUI wants pipeline-specific affordances.

### 7. Manual trigger endpoint — the P5.1a entry point (scheduler is P5.1b)

P5.1a exposes a thin manual trigger: **`POST /pipelines/{id}/run`** loads the definition
from the side table (Decision 8), runs the pipeline via the headless run path **on the
`writer_executor`**, and returns the run's room id + outcome when complete (synchronous,
mirroring how `_write_and_turn` runs a whole turn on the writer before returning). It
**inherits fail-closed auth** — the principal is server-derived (ADR-039 D1), never from
the body. This is the **same execution path** the P5.1b scheduler will fire — the
scheduler will be the *second caller* of one run function, not a second code path.

Minimal definition CRUD ships so there is something to run: **`POST /pipelines`**
(create), **`GET /pipelines`** + **`GET /pipelines/{id}`** (read). Edit/delete may ship
here or with P5.1b. **No** `schedule`/`cron`/`next_fire` surface in P5.1a.

**Access control (R0-A F3): `/pipelines*` is owner-private.** `GET /pipelines/{id}`,
`POST /pipelines/{id}/run`, and any future edit/delete are permitted **only** to the
definition's `owner_user_id`; a non-owner principal gets **403**. `GET /pipelines`
returns only the caller's own definitions. This is the **safer default** for a new
endpoint surface (a definition is a list of URLs/files the server fetches on run); it is
chosen deliberately over the collaborative-room "any-authenticated" posture, and made
explicit the way ADR-039 made attribution explicit. (Sharing can be added later if a
collaborative need appears — opening access is reversible; tightening it after release is
not.)

### 8. Persistence — definitions in a side table, run history in the event log

**Pipeline definitions** are **mutable operational config** → a new `pipelines`
**side table** co-located in the main DB, following the `users`/`sessions` precedent
(P4.5/ADR-039): `pipeline_id` (PK), `owner_user_id`, `definition` (JSON: `sources` +
`analysis_prompts` + `output_config`), `enabled` (default true), `created_at`.
`owner_user_id` is captured from the **creating principal** at definition time
(ADR-039 D1/D6) — the single source of audit ownership. **No** schedule columns
(`cron`/`interval`/`next_fire`) — those are P5.1b.

**Run history** is **append-only fact** → the event log already is this: a run's events
live in its room (Decision 7), threadable by `parent_id`. A thin `pipeline_runs` index
row (`run_id`, `pipeline_id`, `room_id`, `owner_user_id`, `started_at`, `status`)
supports listing. **No new `EventType`** is introduced — the run reuses existing
`OBSERVATION` / `SUMMARY_SNAPSHOT` events (ADR-001 referenced, not amended). Definitions
survive restart by virtue of the side table (the P5.1b scheduler adds boot re-arm of
*timers*; P5.1a has no timer to re-arm).

### 9. Constitutional invariants P5.1a holds (Lens-B contract)

- **Orchestration = code/config, never LLM.** Stage order, fan-out count, source list,
  output routing — all code/config. The only LLM is analyze + reduce content-gen
  (`AGENT_RESPONSE`). **No new routing `LLMPurpose`.**
- **Gate + executor spine byte-frozen.** `_execute_local_call` +
  `score`/`decide_tier`/`emit_gate_decision` zero-diff; the pipeline *reuses* the gate +
  executor, never edits them, never re-tiers a tool, never lowers the floor.
- **No headless actuation in P5.1a.** No HARD/irreversible pending is auto-fired;
  `_writer_approve_helper` + `approval_source` unchanged; `RB-AUTOFIRE` exclusions intact.
- **Single-writer + reader-liveness (ADR-025 D6) preserved.** The pipeline appends on
  the writer; P5.1a adds **no** new background/lifespan task (the scheduler is P5.1b).
- **Room/agent contracts (ADR-010/011/012) untouched** (Decision 6).
- **SSRF/sandbox floors apply to every source read** (Decision 4), including feed URLs.

### 10. Inscribe-before-producer: P5.1b and P5.1c are explicitly out of scope

This ADR is the **first inscription** of the pipeline contract; it is intentionally
scoped to the *safe* slice so later producers extend a written contract:
- **P5.1b (deferred):** the recurring scheduler (cron/interval, next-fire, re-arm), the
  `pipelines` table's schedule columns, restart re-arm of timers (the ADR-040 boot-re-arm
  pattern as a **sibling** scheduler — NOT a generalization of the spine-critical
  countdown sweeper), catch-up semantics, and incremental feed state. Extends this ADR
  (or ADR-042). Adds a second bounded background task (ADR-025 D6 note).
- **P5.1c (deferred):** the headless email actuator authorization — the
  `RB-AUTOFIRE`-beyond crossing (`send_email` is HARD-tier *and* reversibility=3 < floor
  5, so headless email inverts the two guards `RB-AUTOFIRE` installed). Opt-in, per-schedule,
  recipient-allowlisted, owner-attributed, reusing `_writer_approve_helper` as a third
  caller with a new `approval_source="auto_pipeline"` marker; inscribes the
  **`RB-PIPELINE-EMAIL`** residual honestly. Its own isolated dual-lens. Extends this ADR
  (or ADR-043).

## Considered alternatives

### A. Ride the pipeline on the room/event model (a `pipeline` RoomType driven through `dispatch_turn`)

Make the pipeline a special headless "room run": a new `RoomType` + a trivial state
machine, driving the stages through the existing `dispatch_turn` / turn-loop by injecting
synthetic `current_event`s.

**Why rejected.** It fights the grain hardest: the room model's two non-determinisms
(emergent agent set via `should_agent_speak`; result-driven re-dispatch) are exactly what
a pipeline must *suppress*. You would configure the conversational engine to not be
conversational — single-agent rooms, trigger hacks, fan-out faked as sequential turns —
polluting ADR-010/011/012 with a non-conversational special case (Decision 1). Ruled out
by the determinism + contracts-untouched requirements.

### B. Extract a shared, dispatch-pluggable `run_turn_loop` helper used by both `_write_and_turn` and the pipeline

Refactor the bounded re-dispatch loop body (`api/app.py:955-1036`) into a helper
parametrized by a *dispatch function*: the interactive path passes its
`should_agent_speak`-based dispatch; the pipeline passes a forced-single-agent dispatch.
This is the literal "reuse the existing turn-loop, don't rewrite it" reading.

**Rejected (architect-routed, 2026-06-09).** It refactors the **interactive spine path**
— a Lens-B hazard (a behavior-preserving extraction can still regress the interactive
turn, and it enlarges the interactive path's review surface). Decision 2 instead reuses
the two *load-bearing* units (the gate + the executor) verbatim and duplicates only the
~30 lines of trivial bounded-pass scaffolding, keeping the interactive handler
byte-untouched. The architect routed **D2** over this alternative: spine byte-untouched
> DRY, the duplication being ~30 trivial lines.

### C. No source abstraction — wire the existing tools + one new feed tool, LLM-composed

Have the fetch stage be an agent calling `web_fetch` / `read_file` / a new feed tool, with
the LLM composing them.

**Why rejected.** It makes **which sources get read an LLM decision** — non-deterministic,
and violates "orchestration = code, not LLM" (Decision 4, §9). The pipeline's source set
is a fixed configured list, so deterministic fetch is required.

### D. Schedule definitions event-sourced (`SCHEDULE_DEFINITION` events) instead of a side table

Model definitions on the append-only log, edits as supersession events.

**Why rejected (for P5.1a).** Definitions are *mutable operational config* (create / edit
/ disable / delete); the append-only store was designed for *facts*, and modeling mutable
config there means every edit/disable is a supersession event (the store-invariant-#1
friction: no in-place update). The `users`/`sessions` side-table precedent fits exactly
(Decision 8). Run history *is* event-sourced (it is fact). The fuller append-only audit
trail of schedule edits, if wanted, is a P5.1b call.

## Consequences

**Easier:**

- A pipeline run is *deterministic and inspectable* — the stage order, the exact source
  list, and the exact analysis-prompt set are all readable config; "why did this run read
  X / run analysis Y" is a config lookup, not an emergent-dispatch reconstruction.
- The conversational engine is *untouched* — no room/agent contract churn, no
  `should_agent_speak` special cases, no interactive-spine refactor. The gate + executor
  are reused verbatim, so gating correctness is inherited, not re-derived.
- A *safe headless pipeline ships now* — operators get scheduled-analysis value (GUI
  output) with **zero** new authorization surface; the risky email crossing is isolated
  for its own scrutiny (P5.1c).
- The manual trigger and the future scheduler share **one** run path (Decision 7), so
  P5.1b adds a *caller*, not a parallel execution model.

**Harder:**

- ~30 lines of bounded-pass scaffolding are duplicated rather than shared with
  `_write_and_turn` (Decision 2) — a small DRY cost paid to keep the interactive spine
  byte-untouched (revisitable via alternative B).
- A manual run occupies the single writer for its duration (`N × per-branch wall-clock`)
  and can delay interactive turns (Decision 3) — acceptable for operator-initiated,
  infrequent P5.1a runs; P5.1b may add background execution.
- An RSS/Atom parser is genuine new code with its own correctness + security surface
  (malformed feeds, billion-laughs/XXE on XML parsing, feed URLs through the SSRF floor) —
  Decision 4 floors it but it must be tested adversarially (Lens A).
- The pipeline introduces a new side table + a new endpoint surface — more schema + API
  to maintain, and the P5.1b/P5.1c extensions must respect this ADR's seams.

**Reversibility:**

- High. P5.1a is reversible output only + a new isolated package + one side table + read
  /create/run endpoints; nothing in the existing spine is modified. Removing the feature
  is dropping the `pipeline/` + `sources/` packages, the `/pipelines*` routes, and the
  `pipelines`/`pipeline_runs` tables. The contract seams (Decisions 7, 10) are designed so
  P5.1b/c extend rather than rewrite.

## References

- Architect brief / decision-surface: `docs/process/architect-briefs/P5.1.md` (DP0–DP8);
  ratification commit `f720753`.
- Substrate (verify-cited): `api/app.py:933-1044` (`_write_and_turn`, the interactive
  turn-loop), `:285-377` (`_writer_approve_helper`), `:426-489` (`_countdown_sweeper`),
  `:1498-1523` (lifespan); `agents/dispatch.py:56-202` (`dispatch_turn`,
  `should_agent_speak` use); `agents/tool_dispatch.py:60-179` (`process_tool_calls`, the
  gate; `:133-145` the `RB-AUTOFIRE` stamp guards); `tools/executor.py:82` 
  (`execute_pending_tool_calls`); `tools/net_trust.py` (`build_ssrf_client` /
  `_resolve_and_validate`, ADR-035/037); `tools/local.py:62-110` (`_check_path` /
  read_file sandbox); `core/event.py:68-99` (EventType — OBSERVATION/SUMMARY_SNAPSHOT),
  `:214-224` (`approval_source` Literal), `:447-460` (`build_author`/`build_user_author`);
  `core/room.py:19-27` (`RoomType`); `api/auth/users.py:30-67` (side-table precedent);
  `llm/purposes.py:36` (`AGENT_RESPONSE`); `autonomy/scoring.py:54-88` (`ThresholdConfig`).
- Related ADRs: ADR-001 (event model), ADR-010/011/012 (room/agent/dispatch contracts),
  ADR-019 (`connectors/` ground-truth output — the name collision to avoid), ADR-025 D6
  (single writer + bounded background tasks), ADR-028 (executor + single-writer), ADR-033
  (agent turn-loop), ADR-035/037 (network SSRF + egress sandbox), ADR-036 (`send_email`
  HARD posture — unchanged here), ADR-039 (auth/identity), ADR-040 (`RB-AUTOFIRE` — the
  boundary P5.1c steps beyond, byte-intact here).
