---
task_id: P6.8
review: plan-vs-impl
reviewer: senior
verdict: clean
impl_ref: origin/claude/P6.8-impl @ 9e64eba
plan_ref: docs/process/senior-plans/P6.8.md
---

# P6.8 plan-vs-impl — `GET /rooms` + sidebar room list

**Verdict: clean.** Both atoms (P6.8-BE, P6.8-FE) are faithful to the plan. No
plan-out expansion, no spine touch, no new wire type, no `owner_user_id` /
owner-scoping. Reviewed `git diff origin/main...origin/claude/P6.8-impl`
(13 files, +355/-2).

## P6.8-BE — `GET /rooms` (cross-family lens)

| Plan atom | Impl | Verdict |
|---|---|---|
| `EventStore.list_rooms() -> list[Room]`, single `SELECT id,type,state,created_at … ORDER BY created_at ASC`, `Room` rows built like `get_room`, `[]` on empty, after `list_room_ids` | `event_store.py` +20: byte-identical row construction to `get_room` (`id=RoomId`, `type=RoomType`, `state=row["state"]`, `created_at=TimestampMs`); placed directly after `list_room_ids`; docstring mirrors shape | ✅ faithful |
| `@app.get("/rooms", response_model=list[Room])`, no `Depends`/principal, `run_in_executor(ctx.reader_executor, … list_rooms())`, adjacent to `_get_room` | `app.py` +13: exactly that; static `/rooms` registered before `/rooms/{room_id}`; docstring carries ADR-039 D10 cross-ref | ✅ faithful |
| **ADR-039 D10 residual line — additive, existing `RB-AUTHZ` text byte-unchanged, not softened** (the architect's flagged item) | **CONFIRMED PRESENT** (`ADR-039` +1/-1). The `-/+` pair is a same-line append: the existing residual sentence (`…separately built at a D5 checkpoint seam.`) is preserved verbatim, the new `GET /rooms` read-surface-instance sentence is appended after it. Names the enumeration as an RB-AUTHZ instance, defers owner-scoping to DP3b. No reword, no softening | ✅ faithful — the flagged "似乎没有 ADR-039" was a false alarm; the change is in the diff as a 1-line append |
| openapi regen: only additive `/rooms` GET path, no schema churn | `openapi.json` +21/-0 (zero removal lines); only the `/rooms` GET path + `_list_rooms_rooms_get` operation; `Room`/`RoomType` schemas untouched | ✅ faithful |
| Auth assertion: `("GET","/rooms")` in `PROTECTED_ROUTES` (the load-bearing cross-family lens) | `test_constitution.py` +1: added to `PROTECTED_ROUTES` → covered by `test_unauthenticated_gets_401` | ✅ faithful |
| `test_read.py` §1.5: lists all / ASC order / empty→200 `[]` / full Room shape | `TestListRooms` 4 tests covering exactly (a)–(d) | ✅ faithful |
| Store-level test (empty + ASC) | `test_event_store.py` +3 tests: empty→`[]`, all returned, `created_at ASC` | ✅ faithful |

## P6.8-FE — sidebar room list (light track, single-lens)

| Plan atom | Impl | Verdict |
|---|---|---|
| `listRooms(): Promise<Room[]>` mirroring `getRoom` | `client.ts` +4: `request<Room[]>(\`${BASE}/rooms\`)` | ✅ faithful |
| `schema.ts` via `npm run codegen` (consumes BE openapi) | `schema.ts` +29: only the `/rooms` GET path + `_list_rooms_rooms_get` op; clean codegen, no unrelated churn | ✅ faithful |
| `RoomList.tsx` new: fetch on mount, humanized `type`/`state` via `roomTypeLabel`/`roomStateLabel` (no raw wire vocab), click → `setRoom(id,type)`, humanized empty-state | `RoomList.tsx` +46: exactly that; both label fns present (`uiStrings.ts:116,120`); empty-state `暂无房间，请先创建一个。` (humanized); `onClick={() => setRoom(room.id, room.type)}` | ✅ faithful |
| `App.tsx`: render `RoomList` in lobby, **keep `RoomPicker`** | `App.tsx` +2: `<RoomList />` added alongside `RoomCreate` + `RoomPicker`; RoomPicker retained (augment, not replace — matches plan §5 note 2) | ✅ faithful |
| `RoomList.test.tsx`: humanized render / click→setRoom / empty-state | 3 vitest cases asserting humanized labels (raw `free_chat`/`research`/`open` queried null), `setRoom("room_abc","bug_fix")`, empty-state testid | ✅ faithful |

## Forcing-function guards

- **Spine byte-frozen**: no spine file in the diff (`_execute_local_call`, gate, `run_pipeline`, COUNTDOWN, forge-guard all untouched). ✅
- **No new `LLMPurpose`**: zero `LLMPurpose` in diff (pure DB read). ✅
- **Fail-closed preserved**: `PUBLIC_PATHS` unchanged (only docstring mentions); `GET /rooms` stays outside the allowlist, guarded by the new `PROTECTED_ROUTES` entry. ✅
- **No plan-out expansion**: no `owner_user_id`, no owner-scoping, no pagination/filter params, no write path, `RoomPicker`/`list_room_ids`/`_get_room` untouched. ✅
- **One atomic = one commit**: `bad7acf` (BE), `9e64eba` (FE) — clean subjects, not bundled. ✅

## Notes / non-blocking

- `RoomList.test.tsx` test 2 ("clicking … calls setRoom") double-renders and asserts on the second mount (a slightly awkward pattern from the store-mock timing), but it does assert `setRoom("room_abc","bug_fix")` correctly — behavior verified, not a blocker. Gate-level test correctness is for R0-A, not plan-vs-impl.
- Gate verification (ruff/mypy/pytest BE, `npm run gate` FE incl. `codegen:check`) is the impl-stage review lens' job, not plan-vs-impl; this review confirms the **diff matches the plan**.

**No blocking findings. No architect decision required.**
