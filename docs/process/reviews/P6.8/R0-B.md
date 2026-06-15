---
task_id: P6.8
round: R0-B
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 7
verdict_history:
  - clean (2026-06-15, R0-B cross-family)
---

# R0-B cross-family review — P6.8 BE atom (GET /rooms)

**Reviewed**: `origin/claude/P6.8-impl` @ `9e64eba` (BE commit `bad7acf` —
`P6.8-BE: GET /rooms (list all rooms)`). FE atom (`9e64eba` P6.8-FE) is
single-lens R0-A territory — SKIP per ADR-026 (role doc § "Never review dev
harness changes" + brief §5).

**Lens**: auth-enumeration boundary (brief §5 Lens A) + contract/spine
no-regression (brief §5 Lens B). True cross-family — applying outside-Claude
perspective per `dual-lens-r0b.md`: tracing runtime failure modes across the
auth → reader-pool → DB boundary rather than trusting type-level correctness.

---

## Lens preamble

The BE atom is an additive read: one `SELECT` + one FastAPI route returning
the existing frozen `Room` schema. The structural risk is **not** the code
volume (it is small); it is whether the auth posture is genuinely fail-closed
(not relying on "the route isn't in the allowlist" alone — tested
parametrically), whether the reader-pool use is honest (no writer-connection
leak, no WAL-race), and whether the enumeration residual is inscribed without
softening the existing `RB-AUTHZ` text. These are exactly the failure modes
an in-family reviewer trusts the types to catch and a cross-family reviewer
traces at runtime.

---

## Findings

| ID | Sev | File:line | Claim | Investigation |
|----|-----|-----------|-------|---------------|
| G1 | 🟢 | `src/orchestrator/api/app.py:1343` + `tests/api/auth/test_constitution.py:197` | GET /rooms is **outside** `PUBLIC_PATHS = {"/login", "/health"}` (`auth/middleware.py:36-41`); the fail-closed middleware returns 401 for unauthenticated requests by construction. The new `("GET", "/rooms")` entry in `PROTECTED_ROUTES` parametrized test (`test_constitution.py:197`) nails the auth-surface assertion — 401 tested, not assumed. Same posture as GET /rooms/{id}: both any-auth, both no owner-scoping, both no `Depends`/principal param. | Already verified — no action. |
| G2 | 🟢 | `src/orchestrator/core/event_store.py:405-422` | `list_rooms()` uses a single `SELECT id, type, state, created_at FROM rooms ORDER BY created_at ASC` — no INSERT/UPDATE/DELETE. The endpoint (`app.py:1349`) dispatches via `ctx.reader_executor` — not `writer_executor`. Read-only on the reader pool; cannot block the writer or contend on the WAL. Returns `[]` on empty store (no N+1, no exception). | Already verified — no action. |
| G3 | 🟢 | `src/orchestrator/core/room.py:30-45` | `Room` is `frozen=True, extra="forbid"` with exactly four fields: `id`, `type`, `state`, `created_at`. The `response_model=list[Room]` annotation (`app.py:1343`) ensures FastAPI serializes only these fields — no per-user data, no event/agent data, no `owner_user_id` (out of scope per brief). The existing `GET /rooms/{id}` returns the identical shape; the list endpoint only removes the need-to-know-the-id friction. | Already verified — no action. |
| G4 | 🟢 | `docs/decisions/ADR-039-auth-identity-model.md:109` | ADR-039 D10 `RB-AUTHZ` bullet gains exactly **one additive line**: names GET /rooms as a read-surface instance of the already-accepted posture, notes `GET /rooms/{id}` already reads any room, defers owner-scoped visibility to DP3b. Existing residual text **byte-unchanged** — the line appends, does not replace. No softening ("any authenticated user can enumerate all room ids" stated honestly). | Already verified — no action. |
| G5 | 🟢 | spine (cross-file) | `_execute_local_call`, `gate.py` (`score`/`decide_tier`/`emit_gate_decision`), `forge.py`, `run_pipeline`, COUNTDOWN auto-fire, `llm/` — all **zero diff** (`git diff origin/main...origin/claude/P6.8-impl -- src/orchestrator/{autonomy,llm} src/orchestrator/core/{gate,forge,pipeline}.py` is empty). Zero new `LLMPurpose` (no LLM in path — pure DB read). | Already verified — no action. |
| G6 | 🟢 | `src/orchestrator/api/openapi.json` | openapi.json regenerated; the **only delta** is the `/rooms` GET path entry. `Room`/`RoomType` component schemas exist unchanged — no schema churn, no reordering of unrelated entries. Delta matches the brief §4 expectation exactly. | Already verified — no action. |
| G7 | 🟢 | `tests/api/test_read.py:123-169` + `tests/core/test_event_store.py:346-374` + `tests/api/auth/test_constitution.py:197` | Tests cover: (a) store-level — empty → `[]`, all returned, `created_at ASC` order; (b) API-level — empty 200 `[]`, lists all rooms, ordering, full Room shape fields; (c) auth — parametrized 401 via `PROTECTED_ROUTES`. All 105 collected tests pass (full suite green, exit 0). | Already verified — no action. |

---

## Synthesis

The BE atom is a textbook additive read: one query on the existing rooms
table, one route mirroring `_get_room`'s reader-pool pattern, zero spine
touch, zero contract change. The auth posture is fail-closed by the
middleware's construction AND parametrically tested (not assumed). The
enumeration residual lands as a single additive line in the existing D10
ledger without softening the accepted `RB-AUTHZ` text.

No 🔴, no 🟡. No cross-family finding to surface. The impl matches the plan
and brief exactly; the dual-lens framing (brief §5 Lens A + B) produced no
runtime-integration failures the in-family lens would miss on this particular
surface — the additive-read shape is simple enough that both lenses converge
on clean.

---

*Cross-family review. Verdict: clean. 0 🔴 / 0 🟡 / 7 🟢 advisory.*
