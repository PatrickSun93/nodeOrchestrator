---
task_id: P6.8
stage: impl
reviewer: architect-partner (R0-A)
review_kind: R0-A-on-impl
branch: origin/claude/P6.8-impl
commit: 9e64eba
lens: dual-lens — R0-A (∥ R0-B on BE atom); single-lens R0-A on FE atom (R0-B SKIP, ADR-026)
verdict: needs_architect
date: 2026-06-15
---

# R0-A on impl — P6.8: GUI room list (`GET /rooms` + sidebar)

**Verdict: `needs_architect`** — one **non-blocking 🟡 (Y1, FE error-handling)**, routine
(orchestrator-routable α/β). **BE atom clean; no red lines** (no new ADR, spine byte-frozen,
residual correctly inscribed, no scope creep); **all gates green** (BE + FE). Mergeable after a
trivial routing call on Y1.

Reviewed `git diff origin/main...origin/claude/P6.8-impl` @ `9e64eba` (2 commits: `bad7acf`
P6.8-BE, `9e64eba` P6.8-FE) against `docs/process/senior-plans/P6.8.md` + brief Ratification
(`docs/process/architect-briefs/P6.8.md`, 2026-06-15). Read-only on shared `main`; gates in an
isolated detached worktree (`uv sync --all-extras`).

---

## BE atom — `GET /rooms` (cross-family) — **clean ✓**

| Plan/brief requirement | Result |
|---|---|
| `EventStore.list_rooms()` **one query** (avoid N+1) | ✓ single `SELECT id, type, state, created_at FROM rooms ORDER BY created_at ASC`; no per-row `get_room` loop |
| Builds `Room` rows **exactly like `get_room`** | ✓ byte-identical construction (`id=RoomId`, `type=RoomType`, `state=row["state"]`, `created_at=TimestampMs`); `[]` on empty store; docstring mirrors `list_room_ids` |
| `GET /rooms` thin wrapper mirroring `_get_room` | ✓ async, `response_model=list[Room]`, `run_in_executor(ctx.reader_executor, lambda: ctx.get_reader_store().list_rooms())`; placed before `/rooms/{room_id}` |
| **Auth-protected (401 unauth)** — *not* added to allowlist | ✓ `middleware.py` **untouched** (`PUBLIC_PATHS = {/login,/health}` intact); no `Depends`/principal param — fail-closed by construction |
| **The load-bearing auth-enumeration assertion** | ✓ `("GET", "/rooms")` added to `PROTECTED_ROUTES` (`test_constitution.py:196`) → parametrized `test_unauthenticated_gets_401` now covers it |
| `created_at ASC` | ✓ in query + asserted by `test_rooms_ordered_created_at_asc` (exact r1/r2/r3 order, stronger than a sorted check) |
| **ADR-039 D10 RB-AUTHZ residual line** (ratify-required) | ✓ **present and correct** — see note below |
| `openapi.json` regen — additive only | ✓ only the new `/rooms` GET path entry; `$ref: Room` reuses frozen schema; zero schema churn |
| Tests: API (empty→200`[]`, list-all, ASC, full-Room) + store-level | ✓ `TestListRooms` (4) + `test_list_rooms_{empty,all_returned,ordered…}` (3) |

**On the architect's flagged concern** ("git diff 只看到 app.py+event_store.py，没看到 ADR-039
—若缺则 flag"): **the ADR-039 D10 line IS in the diff and is correct.** The existing `RB-AUTHZ`
bullet text is **byte-unchanged** (identical up to `…at a D5 checkpoint seam.`); the new content
is appended as additional sentences on the same bullet line — the `2 +-` in `--stat` is git's
line-level representation of an in-place append, **not** a reword/softening. It names `GET /rooms`
as a **read-surface instance** of the accepted posture ("any authenticated user can enumerate all
room ids — the same trust as `GET /rooms/{id}`… owner-scoped visibility is future work (DP3b)"),
cross-referenced from the endpoint docstring. Matches the plan's "additive line only, existing
text byte-unchanged" exactly. Concern **resolved**.

**Dual-lens (BE):** Lens A (auth/enumeration boundary) — exposes *exactly* the accepted all-rooms
enumeration and nothing more (no per-user data, no write, no field beyond frozen `Room`),
fail-closed, residual honestly inscribed. **Boundary not widened.** Lens B (contract/spine) —
additive route, frozen `Room` reused (zero new wire type), `openapi.json`⟷`schema.ts` lock holds,
spine byte-frozen, zero LLM. **No leak beyond an additive read.**

---

## FE atom — sidebar room list (single-lens R0-A, R0-B SKIP) — **one 🟡 (Y1), else ✓**

| Plan/brief requirement | Result |
|---|---|
| `listRooms(): Promise<Room[]>` mirroring `getRoom` | ✓ `client.ts:70` |
| `schema.ts` codegen regen (consumes BE `openapi.json`) | ✓ additive `/rooms` GET path; **`codegen:check` clean** (byte-matches committed) |
| `RoomList.tsx` — humanized `type`/`state`, **no raw wire vocab** | ✓ `roomTypeLabel(room.type)` + `roomStateLabel(room.state)` (ADR-026 D3/HR#3 invariant satisfied) |
| Click → join via `setRoom(room.id, room.type)` (same as `RoomPicker`) | ✓ |
| Empty list → friendly empty-state (humanized) | ✓ `暂无房间，请先创建一个。` |
| `App.tsx` — render in lobby, **keep `RoomPicker`** (augment) | ✓ `RoomList` added alongside `RoomCreate`+`RoomPicker`; `RoomPicker` retained |
| Hardcoded UI copy (`现有房间` heading) | ✓ **consistent with established pattern** — siblings `RoomCreate`/`RoomPicker` hardcode their headings inline; only wire vocab routes through `uiStrings` (cf. `App.tsx` `或者` divider). Not a finding |
| vitest tests (renders / click→setRoom / empty-state) | ✓ all three present + passing |

### 🟡 Y1 (FE, minor) — `RoomList` fetch lacks a `.catch()`, diverging from the sibling error-handling pattern

`RoomList.tsx`:
```ts
useEffect(() => {
  listRooms().then(setRooms).finally(() => setLoading(false));
}, []);
```
No `.catch`. Both siblings wrap their API call in `try { … } catch (err) { setError(…) }`
(`RoomCreate.handleCreate`, `RoomPicker.handleJoin`). On a **non-401** fetch failure (network /
5xx), `RoomList` produces (a) an **unhandled promise rejection**, and (b) the **same "暂无房间"
empty-state** as a genuinely empty store — a misleading "no rooms" where the truth is "fetch
failed." (401 is fine — handled globally by `set401Handler`.)

- **Non-blocking; not a plan violation.** The FE acceptance criteria (renders / click / empty-state)
  are all met; **no criterion requires a fetch-error UI**, and the gate passes (tests mock
  `listRooms` with `mockResolvedValue`, never the reject path).
- **Lean:** α — a 1-line `.catch` to match siblings (distinct error/empty state) is cheap; **or**
  β/γ — accept for the light-list track (passive on-mount list, no stated error-UI need). **Routine
  — orchestrator can route α/β; not an architect red line.**

### Non-blocking observations (NIT — no routing needed)
- `RoomList.test.tsx` test #1 asserts the **negative** (no raw wire vocab — the load-bearing
  ADR-026 check, present ✓) + button count, but does not **positively** assert the specific
  humanized label text. Negative assertion is the important one; positive would be marginally
  stronger.
- test #2 (click→`setRoom`) is convoluted (double render + a redundant first click) but ultimately
  asserts the correct contract `setRoom("room_abc","bug_fix")`. Could be simplified. No
  coverage/correctness impact.

---

## Constitutional guards (all ✓)

| Guard | Result |
|---|---|
| **Spine byte-frozen** (`_execute_local_call`, gate `score`/`decide_tier`/`emit_gate_decision`, forge-guard, `run_pipeline`, COUNTDOWN auto-fire) | ✓ no spine file in the diff (13 files: ADR-039, app.py, openapi.json, event_store.py, 3 test files, 6 FE files) |
| **No new `LLMPurpose`** | ✓ grep clean (zero LLM — pure DB read) |
| **No `owner_user_id` / owner-scoping** (out of scope) | ✓ grep clean |
| **Fail-closed preserved** (`PUBLIC_PATHS` untouched) | ✓ `middleware.py` not in diff |
| **Honest residual not softened** | ✓ ADR-039 D10 additive only, existing text byte-unchanged |
| **Atomic split (RC-17: one atom = one commit/subject), BE → FE** | ✓ `bad7acf` BE / `9e64eba` FE |

## Gates (isolated worktree @ `9e64eba`, `uv sync --all-extras`)

- **Backend:** `ruff check` ✓ · `ruff format --check` ✓ (310 files) · `mypy` strict, `files=[src,tests]`
  ✓ (no issues, 310 files) · `pytest` full suite ✓ (exit 0; the 3 P6.8-relevant files = 90 passed).
  *(Only warning: pre-existing Starlette/httpx `TestClient` deprecation — environmental, unrelated.)*
- **Frontend:** `npm run gate` ✓ (exit 0) — lint · format:check · typecheck · test (110 passed / 11
  files) · **codegen:check clean** (regenerated `schema.ts` byte-matches committed → contract lock holds).

---

## Routing summary (for synthesis)

```
BE atom (cross-family): clean — no findings. Auth-enumeration assertion + ADR-039 D10
  residual both present and correct. Architect's "is ADR-039 missing?" concern → resolved.

🟡 Y1 (R0-A, FE): RoomList fetch has no .catch → unhandled rejection + misleading empty-state
   on non-401 failure; diverges from RoomCreate/RoomPicker try/catch. Non-blocking; plan
   requires no error-UI; gates green.
   → lean α (1-line .catch to match siblings) | β/γ (accept, light-list track)
   → routine — orchestrator routes; NOT an architect red line.

NITs (no routing): two FE test-quality notes (positive-label assertion; test #2 convolution).
```

Nothing escalates to the architect (no new ADR, no spine, no residual-honesty issue, no scope
change). Pending R0-B (BE) + senior plan-vs-impl for synthesis.

*Authored by architect-partner (R0-A). Verify-cited vs `9e64eba`; gates run in detached worktree.*
