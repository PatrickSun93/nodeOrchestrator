---
task_id: P2.5
round: R0-A-on-plan
verdict: clean
findings_count:
  red: 0
  yellow: 4
  green: 9
verdict_history:
  - verdict: needs_architect
    at_commit: 3934d81
    findings_count: { red: 0, yellow: 4, green: 9 }
    note: initial R0-A-on-plan (in-family); the constitutional core (no LLM in selection/ranking/ordering — the highest-risk surface) is CLEAN + AST-guarded; Y1 (leave-time content-gen surface + the LLM-free-guard scope are tangled) is the only substantive 🟡; Y2–Y4 are low refinements.
  - verdict: clean
    at_commit: senior-revision (plan-stage routing absorption)
    findings_count: { red: 0, yellow: 4, green: 9 }
    note: 'Y1+Y2+Y3+Y4 all α-absorbed (RC-10 + dual-lens Step 5; Y3 dual-lens ≡ R0-B Y1). Y1 — ARCHIVE_SUMMARY_RENDER content-gen purpose added (llm/purposes.py + ADR D5/D9), derive_query_tags pinned to digest.py, LLM-free guard re-scoped by named function. Y2 — import guard covers core/+memory/+derived/+llm/. Y3 — new_since_leave typed NewSinceLeaveItem + first-visit=[]. Y4 — Q2 decision_trace=N/A + Q4 6-cat walk in PR. r0b-G2 render-output-validation is a forward hook, not bundled.'
---

# P2.5 R0-A on plan (architect-dispatched pre-impl review, in-family)

| Field | Value |
|---|---|
| Round | R0-A-on-plan (architect-dispatched per RC-9; in-family) |
| Artifacts | `senior-plans/P2.5.md` + `ADR-021-room-reentry-catchup.md` (Proposed) vs `origin/main` substrate + brief P2.5 |
| ADR status | ADR-021 left **Proposed** — this review informs accept; I did not accept (architect-only). |
| Cross-family | `requires_cross_family_review: true` — r0b R0-B runs after me on the shared tree; I leave it clean. |

## Verdict: needs_architect

**The design is fundamentally sound, and the thing you were most worried about is clean.** The constitutional crux — *no LLM in selection / ranking / ordering* — holds and is **structurally enforced**: every decision (which VK via the deterministic `lookup_verified_knowledge` scope+tag filter, which entities/prefs via code filters, the "what's new" timestamp diff, the tag-derivation) is pure code; the single LLM call (`render_reentry_prose`) phrases the already-frozen `ReentryDigest` and is confined to `render.py` by an AST guard. I verified the `LLMPurpose` taxonomy contains **no routing/judgment purpose** to misuse (`purposes.py` — all values are content-gen or candidate-to-human-pool), and `REENTRY_DIGEST_RENDER` is content-gen. This is the strongest Principle-11 expression in the project so far.

**Four 🟡, one substantive (Y1).** Y1 — the *leave-time* content-gen surface (the archive summary) and the LLM-free-selection guard's scope are **tangled and under-specified** — is architect-relevant (it may imply a second ADR-gated content-gen purpose, touching ruling (c)/(a)'s scope). Y2–Y4 are low (guard completeness, `new_since_leave` precision, Q2/Q4 labeling) — senior-absorbable. Nothing blocking.

## The six named checks

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | All catch-up **decisions code-driven**; no hidden LLM judgment/ranking; LLM only content-gen over a pre-selected/ordered set; `LLMPurpose` content-gen-only | **clean (G1)** | Selection/ordering/diff/tag-derivation all code (ADR D3/D6; plan P2.5-4). LLM confined to `render_reentry_prose` (D4), AST-guarded LLM-free selection (P2.5-5 guard ii). Verified `purposes.py`: AGENT_RESPONSE / SNAPSHOT_SEMANTIC / *_CANDIDATE / *_PROPOSAL / TOOL_OUTPUT_INTERPRET — **none is routing/judgment**; `REENTRY_DIGEST_RENDER` is content-gen, consistent. |
| 2 | Consumer **outside `memory/`** + dependency direction (`memory/`/`core/` don't import consumer) | **clean; Y2 (guard completeness)** | `orchestrator/reentry/` is new + outside `memory/` (verified no existing `reentry` import); imports `memory/+derived/+core/+llm/`; import guard (i) mirrors the existing per-package `*-no-import` `test_constitution`s. **Y2: guard names only `memory/`+`core/` — should cover all upstream (`derived/`, `llm/`).** |
| 3 | tag-derivation is **code** (lookup requires non-empty tags) | **clean (G3)** | `derive_query_tags` = code union of the room's hypotheses' canonical `topic_tags` (D6); empty → **skip** the lookup (never passes `[]`, which `lookup.py:33` raises on — verified). LLM-relevance explicitly rejected (ADR considered-alternatives). |
| 4 | leave/return **marker** holds (snapshot is derived, not persisted) | **clean (G4); Y1 (the *summary*, not the marker)** | `reentry_marker(room_id,user_id,last_seen_ts)` persisted table (D5) — correctly identifies that `produce_snapshot` is derived (verified) so a stored last-seen pointer is needed; upsert at leave, diff at return; EventType-marker considered + rejected soundly. (The *marker* is sound; the leave-time *content-gen summary* is Y1.) |
| 5 | consumer-reader **frozen model + `extra="forbid"`** | **clean (G5); Y3 (`new_since_leave` precision)** | `ReentryDigest` frozen + `extra="forbid"` (D7, P2.5-2 AC#1); `generated_at` clock-injected (`now` param) → deterministic. **Y3: `new_since_leave: list[dict[str,Any]]` is weakly typed + its fact-type coverage is under-specified.** |
| 6 | three rulings (one slice / LLM render) + contributing Q1–Q5 | **rulings clean (G6); Q1/Q3/Q5 clean (G7); Y4 (Q2/Q4)** | (a) one slice + (b) dual-lens dispatched + (c) LLM render ships — all implemented (§5, P2.5-5). Q1 (render is the only LLM, justified), Q3 (5-surface), Q5 (discriminating-by-stable-labels, RC-25) addressed. **Y4: Q2 (decision_trace) unaddressed; Q4 6-category walk embedded but unlabeled.** |

## Findings

### Y1 🟡 — the leave-time content-gen surface + the LLM-free-selection guard scope are tangled (the only substantive finding; architect-relevant)

Three intertwined gaps in the **leave-time half** (decision-a's half-1, the less-developed side):

1. **The archive summary's content-gen path is ambiguous.** P2.5-3 says `one_line_summary`/`spinoff_questions` are "produced **via the render path / passed in**" — two different things, unresolved. These are a *second* content-gen surface, **distinct** from the re-entry welcome-prose: rendering a closing room into a one-line summary ≠ phrasing the re-entry digest. Reusing `REENTRY_DIGEST_RENDER` for it would be the same semantic-mismatch the ADR itself rejects for `SNAPSHOT_SEMANTIC` (D9). So either (i) P2.5 **generates** it → it needs its **own** content-gen `LLMPurpose` (e.g. `ARCHIVE_SUMMARY_RENDER`), which is **ADR-gated** (ADR-021 would have to add it), or (ii) it is **passed-in / test-injected** with real generation **deferred to P2.6** — in which case the plan should say so and reconcile with the brief's "离开房间时生成 catch-up 摘要" + ruling (c) (does (c)'s "MVP includes the LLM render" cover *only* the re-entry prose, or also the leave summary?).
2. **`derive_query_tags` placement is internally inconsistent.** P2.5-3 puts it in `reentry/leave.py`; ADR D6 + the P2.5-5 guard (ii) scope it to `reentry/digest.py`. Pick one.
3. **The LLM-free guard must target the selection *functions*, not a file.** Because `leave.py` may legitimately host the content-gen summary (per #1), a blanket "`digest.py` is LLM-free" guard is both wrong-scoped (misses `derive_query_tags` if it lives in `leave.py`) and unable to allow `leave.py`'s content-gen. The guard should assert the named selection functions (`assemble_reentry`, `derive_query_tags`, the diff) are LLM-free *wherever they live*, leaving the render + the archive-summary functions as the allowed LLM sites.

**Lean (surface, not decide):** resolve the three together — pin the leave-summary as **(i)** a dedicated ADR-021-added content-gen purpose *or* **(ii)** explicitly passed-in/deferred-to-P2.6; fix `derive_query_tags`' canonical home; and scope the LLM-free guard to the selection functions. **Architect: is a second content-gen purpose (the archive summary) in P2.5 scope** (ADR addition + ruling-(c) implication), **or is leave-time summary generation deferred to P2.6** (P2.5 persists a passed-in/test-injected summary)? That call resolves all three.

### Y2 🟡 (low) — import guard (i) should cover all upstream layers, not just `memory/`+`core/`

`reentry/` is the consumer; **nothing upstream** should import it — but the guard (i) names only `memory/`+`core/`. `derived/` and `llm/` are also upstream (reentry imports them) and should be in the no-import-`reentry` assertion. **Lean:** extend guard (i) to `core/`+`memory/`+`derived/`+`llm/`. Senior-absorbable.

### Y3 🟡 (low) — `new_since_leave` is the least-specified surface (and weakly typed)

`new_since_leave: list[dict[str, Any]]` (D7) — the milestone's "here's what changed" UX — leaves under-pinned (a) **which fact-types** it includes (post-marker VK? entities? events via snapshot? all?) and (b) the **descriptor schema**. The `list[dict[str,Any]]` weak typing is precedented (ProjectArchive.decision_log) so acceptable, but a **typed descriptor sub-model** would make the discriminating e2e (P2.5-6 AC#3) sharper. **Lean:** senior pins the fact-type coverage + descriptor shape, with a discriminating test per included type. Senior-absorbable.

### Y4 🟡 (low) — Q2 (decision_trace) unaddressed; Q4 6-category walk unlabeled

§4's forcing-functions cover Q1/Q3/Q5 explicitly but **omit Q2** (decision_trace) — ironic given the "code decides" crux invites "where's the trace?". It is almost certainly **N/A** (the catch-up's selection is deterministic *composition* — fetch+filter+timestamp-diff — not a scored/ranked/gated decision; the trace is the query itself), but the plan should **say so** rather than silently omit it (contributing.md's mark-N/A-with-reason discipline). Q4's 6-category coverage is present *in the acceptance criteria* but not labeled as the Q4 walk (defer the labeled walk to the PR commit). **Lean:** add a one-line Q2-N/A statement; keep Q4 for the PR. Senior-absorbable.

## What holds — verified clean (G1–G9)

- **G1 — the constitutional core.** Selection/ranking/ordering/diff/tag-derivation all code; LLM confined to a single content-gen render; AST guard enforces LLM-free selection; the `LLMPurpose` taxonomy has no routing/judgment purpose to misuse (verified `purposes.py`). The strongest Principle-11 expression yet.
- **G2 — placement + dependency direction** (modulo Y2): `reentry/` outside `memory/`; correct import direction; guard idiom established.
- **G3 — tag-derivation code-driven**, empty-skips the lookup (never passes `[]`); LLM-relevance rejected.
- **G4 — the marker mechanism** correctly fills the snapshot-is-derived gap; EventType-marker considered + rejected soundly.
- **G5 — `ReentryDigest` frozen + `extra="forbid"`**, clock-injected → deterministic.
- **G6 — the three rulings implemented** ((a) one slice, (b) dual-lens dispatched, (c) render ships).
- **G7 — Q1/Q3/Q5** addressed (render-only LLM justified; 5-surface; discriminating-by-stable-labels).
- **G8 — render feasibility verified**: `LLMRequest(purpose, caller_agent_id, system, messages)` shape (types.py:166) + `LLMRouter.call` (protocol.py:68, async — render/`reenter` will be async, mirroring `agents/dispatch.py`) support the render as specified.
- **G9 — substrate claims verified**: `lookup_verified_knowledge` raises on empty tags (lookup.py:33); `produce_snapshot` derived/pure; `list_room_topic_tags` feasible (`hypothesis` carries `room_id`+`topic_tags`); RC-26 recurrence (the marker upsert mirrors the P2.4 preference upsert — same single-connection-safe-today posture, consistent with the existing deferral, **no new action**).

## What I did NOT do

- Did not accept ADR-021 (architect-only).
- Did not decide Y1's content-gen-purpose / scope question — surfaced with a lean for you to rule.
- Did not touch the tree beyond this review file (r0b R0-B runs next on the shared tree).
