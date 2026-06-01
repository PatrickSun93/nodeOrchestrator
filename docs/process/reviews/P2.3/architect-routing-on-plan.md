---
task_id: P2.3
kind: architect-routing-on-plan
date: 2026-05-31
stage: plan
adr: ADR-019
reviews_acked:
  - R0-A-on-plan.md          # architect-partner — 0🔴 1🟡 6🟢
  - R0-B-cross-family.md     # cross-family (deepseek) — 0🔴 1🟡 6🟢
decisions:
  Y1: α (resolve the reader's open skip-or-raise toward NOT-skip; drop the append-time-unreachable malformed-metadata skip branch)
---

# P2.3 architect routing — plan stage (Y1 → α)

**Architect decision (this session, chat 2026-05-31, architect = Peidong):** the plan-stage joint verdict carried **one** 🟡 — flagged by **both** lenses (architect-partner R0-A + cross-family R0-B), independently, with zero divergence. Architect routes **Y1 → α**. No `src/` design change; a one-line acceptance-criterion precision.

**Headline (the reason this dispatch existed):** this is the **highest Principle-5 stakes slice in the project** — rule (c) literally validates "truth," the single most likely place to smuggle LLM-judgment into a code decision. **Both lenses independently confirm the Principle-5 boundary is clean: rule (c) is a deterministic code-predicate over a typed verdict, with NO LLM-judgment leak into `memory/`.** The cross-family lens traced the exact execution path (connector → `EventStore.append` → `validate_metadata` → event log → reader's `verdict == "confirmed"` check) and confirmed the relocation is a *genuine architectural boundary, not a rationalization that moves the same LLM call one import away while staying inside the trust boundary.* **0🔴, 6🟢 confirmed by both lenses.** ADR-019 is accept-worthy once Y1 is absorbed.

This file is the **signal artifact for the senior revision session** (plan stage). Senior picks P2.3, reads this + the two plan-stage reviews + the current plan + ADR-019, applies the single routed action, and pushes a revision commit on `claude/P2.3-plan`. Then the architect accepts ADR-019 (status bump) — the gate is honest (ADR-019 parses `proposed`; RC-23 clear), so the bump genuinely gates `awaiting_architect_accept → awaiting_junior_impl`.

## Issue map (1 issue, both lenses)

| Issue | Raised by | Confidence | Route |
|---|---|---|---|
| **Y1** — reader's "skip malformed metadata" branch guards an append-time-unreachable state | R0-A Y1 **+** R0-B Y1 (both lenses, incl. cross-family source-verification) | high (zero divergence) | **α** |

## Per-issue routing

### Y1 → α — resolve the reader's open "skip or raise" toward NOT-skip (test/spec precision; no `src/` design change)

**Finding (R0-A Y1 = R0-B Y1, both lenses independently source-verified):** plan P2.3-3 AC#7 lists, among the reader's cleanup cases, *"malformed metadata JSON (skip or raise — pin: skip a row whose metadata lacks the keys, since a connector contract violation should not break the reader; document)."* Two problems, both small:

1. **The state is unreachable by construction.** `EventStore.append` calls `validate_metadata(event.type, event.metadata)` on **every** append (`event_store.py:300`; `append_in_transaction` at `:273`), and `ExternalValidationMeta(_BaseMeta)` is `frozen=True, extra="forbid"` (`event.py:120-121`). A malformed `external_validation` event (missing / extra / ill-typed field) raises `MetadataValidationError` at write time and **never lands in the `events` table** through the sanctioned path. The reader cannot encounter a row "whose metadata lacks the keys."

2. **"Skip" silently hides the only case it could ever fire on.** The single way such a row exists is a raw `INSERT` bypassing `EventStore.append` — a far deeper invariant break than this reader should paper over. Silently skipping it is the "fail-soft hides the bug" anti-pattern the project rejects elsewhere (cf. ADR-018 D4's empty-tag `ValueError` — fail-loud on a producer bug). The branch protects an impossible state, and its skip behaviour would conceal the very upstream break a guard should surface.

**Why α (not β-accept):** an acceptance criterion that specs a defensive branch for an append-time-impossible state (a) adds dead code, (b) bakes in a "skip" default that would hide a real upstream bypass, and (c) reads as not-quite-recognising that append-time `validate_metadata` is the actual guard. Cheap to land cleanly; both lenses (one cross-family) traced the same append-time fact to the same conclusion → high confidence.

**Action (senior revision):**
- **Drop the defensive malformed-metadata skip branch** from the reader's spec (P2.3-3 AC#7). The reader `json.loads` the metadata of events **already validated at append time** by `validate_metadata` + `extra="forbid"`; it should trust that contract.
- Add a one-line note in the plan (and optionally ADR-019 D2) that `external_validation` metadata is **guaranteed well-formed by append-time `validate_metadata`**, so the reader does no defensive metadata-shape handling.
- **If belt-and-suspenders is still wanted**, the correct shape is **raise** (a constitutional canary that surfaces an upstream `EventStore.append`-bypass loudly), **not silently skip** — mirroring the project's fail-loud posture. Architect's stated preference: resolve the plan's open "skip or raise" toward **NOT-skip** (drop preferred; raise acceptable; silent-skip not).
- **No `src/` design change** — the representation, the deterministic predicate, the pure-derivation reader, and the advisory orthogonality are all correct as designed (6🟢, both lenses). This is one acceptance-criterion line.

## Non-routing affirmations (no α/β/γ — the design is correct)

Both lenses independently confirmed, for the record (no action):
- **Principle-5 boundary clean** (R0-A G1 / R0-B G1) — judgment relocated to the connector; `memory/` reads a typed verdict field; no LLM enters the boundary. **The load-bearing check, clean from two families.**
- Representation (i) event + pure-derivation reader correct (Principle-1 + connector-decoupling + derive-don't-materialize) · advisory-by-construction (D10/D11 untouched) · confirmed-only + don't-touch-`status` + distinct provenance · AST orthogonality guard (RC-24, not substring) + discriminating determinism test (P2.2 Y1→α) · every constitutional cite source-verified (18→19 exact, deliberate-dup `DecisionMeta:156`, `TYPED_METADATA:322`, no `len(EventType)` test) — by **both** reviewers.

## Net

- **1 routed action:** Y1 → α (drop the unreachable malformed-metadata skip; trust append-time `validate_metadata`; raise-not-skip if belt-and-suspenders). Test/spec precision, no `src/` design change.
- **0 🔴; 6🟢 confirmed by both lenses; Principle-5 boundary clean from two independent families** — the highest-confidence plan-stage result in the P2 series.
- After the Y1 revision lands + the senior bumps the review verdicts, the architect accepts ADR-019 (honest gate) → `awaiting_junior_impl`.

State: per ADR-008, this routing moves P2.3 to senior-revision territory; senior absorbs Y1 on `claude/P2.3-plan`, bumps verdicts, then architect accepts ADR-019.
