---
task_id: P4.5
review: plan-vs-impl
reviewer: senior planner
date: 2026-06-06
plan: docs/process/senior-plans/P4.5.md
impl_branch: claude/P4.5-impl
impl_commits: [4e34c7b, 21eb0be, 40f7d2a, 5b2729f, 8a0e1ec, bbafa86, a07a932, 7924b36]
rework_commits: [7009f2f, 1cf34f9, adf7053, f114522, 5add58b, ca8ca1c]
verdict: clean
verdict_history:
  - round: 1
    verdict: blocking
    date: 2026-06-06
    findings_count: { red: 1, yellow: 2, green: 3 }
    summary: 4 e2e tests broken by auth boundary (red pytest gate) + WS unauth test absent + flaky concurrent-subscriber test
  - round: 2
    verdict: clean
    date: 2026-06-06
    summary: >-
      RC-10 verdict-bump re-review. F1/F2/F3 all resolved by junior rework
      (RW1 7009f2f, RW2 1cf34f9, RW5 5add58b); CANONICAL gates re-run by senior
      — ruff pass, mypy pass (275 files), full pytest 2221 passed / exit 0 / 100%.
findings_count: { red: 1, yellow: 2, green: 3 }   # round-1; all resolved in round-2
gates:                  # round-2 re-run by senior (full suite, not subdir)
  ruff: pass
  mypy: pass            # Success: no issues found in 275 source files
  pytest: pass          # 2221 passed, exit 0, 100% — F1/F2/F3 all green
---

# Senior plan-vs-impl — P4.5 (auth / multi-user / remote-bind)

**Lens:** the only audit surface that knows what the *plan* said. External R0
reviewers see deliverable-vs-spec; I see impl-vs-plan — the plan-mandated
acceptance criteria + plan-implied invariants (the gates the plan's own
forcing functions require to be green).

**Method:** read the plan (incl. the absorbed A-2/Y1/A-1/M3/B-1/B-2/M1/M2) +
all 8 impl commits `4e34c7b..7924b36`, then ran the CANONICAL gates myself
(ruff + `uv run mypy` files=src,tests + full `pytest`) per dispatch.

**Headline:** the *product code* is faithful to the plan on every atomic — the
fail-closed boundary, the server-derived principal, the forge guards, the
nullable-`approver_user_id` landing, the loopback-aware bind guard, and the
ADR annotations all match the plan + ratified leans. **But the impl ships a RED
canonical pytest gate**: the auth boundary it correctly adds breaks 4 existing
e2e tests that were never re-wired to authenticate. The plan's own forcing
functions (5-surface scan + green gates, §4) are therefore unsatisfied.
**Verdict: blocking.**

---

## Per-atomic faithfulness (What / Where / Acceptance)

| Atomic | Plan intent | Impl | Verdict |
|---|---|---|---|
| **P4.5-1** | users table + scrypt + first-account CLI | `auth/users.py` (scrypt n=2^14, `os.urandom(16)` salt, `hmac.compare_digest`, hash never escapes, `disabled` blocks verify) + `admin.py create-user` (stdin/env pw, out-of-band) + `count_users` | ✅ faithful |
| **P4.5-2** | sessions + token + `Principal` | `auth/session.py` (`secrets.token_urlsafe(32)`, expired/revoked→None, token stored SHA-256-hashed, both carriers → one `Principal`) + `auth/principal.py` | ✅ faithful (token=SHA-256 not scrypt — documented + correct for a 256-bit random token; plan only required "hashed") |
| **P4.5-3** | fail-closed boundary + login/logout + WS pre-accept + **shared construction-time `configure`** | `_configure()` called by **both** `create_app` AND `_make_test_app`; `ctx` on `app.state` at lifespan / immediately; middleware reads `request.app.state.ctx`; WS rejects **before** `accept()` via `close(1008)`; cookie `HttpOnly+Secure+SameSite=Strict` | ⚠️ **product code faithful**; Y1 wiring seam honored exactly (tested-app == shipped-app); but see **F1 / F2** on test surface |
| **P4.5-4** | `author="user"`→`user:<id>`, `is_valid_author` generalised, `build_user_author`, server-derived | `event.py` regex `^(user\|user:<id>\|system\|agent:<id>)$` (bare `user` kept), `build_user_author` raises on empty, `app.py:486` stamps from `request.state.principal` not body; B-1 categorization done (CLASS A=test_intent/test_failure_modes; CLASS B=direct `Event(author="user")` fixtures) | ✅ faithful (blind spot structurally closed: fail-closed middleware ⇒ no bare-`user` silent-pass path) |
| **P4.5-5** | confirm provenance = optional nullable on **existing** meta, no new event type, idempotency untouched, executed TOOL_CALL stays agent-authored | `approver_user_id: str \| None = None` on `ToolCallMeta` + `ToolCallCancelledMeta`; stamped from principal not body; `PENDING_RESOLUTION_TYPES`/still-pending scan byte-unchanged; TOOL_CALL author = `agent:<initiating_agent>` unchanged; D5 seam no-op comment | ✅ faithful (field name `approver_user_id` > plan's loose "user_id" — clearer, semantically identical) |
| **P4.5-6** | fail-closed remote-bind (loopback-aware), CORS=future-only, TLS=deployment, rate-limit=deferred-residual | `__main__.py` `_is_loopback` (127.0.0.0/8 + ::1 + `localhost` via `ipaddress.is_loopback`) + `_check_remote_bind_guard` (no DB / 0 users → `sys.exit(1)` loud); CORS/TLS/rate-limit dispositions documented | ✅ faithful (M1/M2/A-2 absorbed; rate-limit deferred per §5 #3 option) |
| **P4.5-7** | 13 Lens-A/B guards as tests | `test_constitution.py`: forge (#1), fail-closed 7-route parametrize + new-route-default (#2 HTTP), expired/revoked (#3), pw/token hashed (#4/#5), no-unauth-create (#6), gate identity-blind empty-diff (#7), no-new-LLMPurpose (#8), `is_valid_author` exhaustive (#9), confirm idempotency (#10), reader-liveness (#11), production-wiring (#12), authenticated-path author (#13) | ⚠️ 12 of 13 present + green; **F2: guard #2's WS half is missing** |
| **P4.5-8** | annotate ADR-025/026/030/038 | All four annotated with `**[Annotated P4.5 → ADR-039, Accepted 2026-06-06: …]**`; residuals (`RB-AUTHZ`, TLS-at-deployment, deferred-D2, role model) named-not-softened | ✅ faithful + honest |

Atomic↔commit 1:1 (RC-17): 8 atomics → 8 commits, each subject-named. ✅

---

## Findings

### F1 — 🔴 BLOCKING: auth boundary breaks 4 e2e tests; CANONICAL pytest gate is RED

`tests/tools/test_e2e.py` builds the app via `_make_test_app(ctx)` and drives
the **now-protected** routes (`POST /rooms`, `POST /intent`, `GET /events`,
`POST /confirm`) through a **bare** `TestClient(app)` — no bearer token, no
session cookie, and its local `_make_ctx` creates **no user**. After P4.5-3 the
fail-closed middleware returns **401**, so `.json()["id"]` raises `KeyError`
and the confirm-actuate assertion fails:

```
tests/tools/test_e2e.py:181:  KeyError: 'id'      # /rooms → 401
FAILED test_e2e_local_auto_tool_appends_tool_result
FAILED test_e2e_mcp_auto_tool_appends_tool_result_and_observation
FAILED test_e2e_hard_mcp_tool_not_executed                 (KeyError)
FAILED test_e2e_apply_edit_confirm_actuates                (AssertionError :396)
```

**Why this is the plan-vs-impl unique find:** the boundary itself is *correct*
— "every non-public route → 401" is exactly P4.5-3's acceptance. The defect is
that the plan's **promotion-impact grep (P4.5-4 / §4 forcing function) was
under-scoped**: it enumerated `author=="user"` *assertion* sites but not the
broader ripple — *every test that drives a now-protected route must
authenticate*. The grep covered `tests/api/*` (re-wired via the conftest
fixture) but **missed `tests/tools/test_e2e.py`** (the only app-building test
file outside `tests/api/` — confirmed by `grep -rln '_make_test_app\|create_app(' tests/ | grep -v tests/api/`).
The junior's per-commit "149/308 tests green" claims ran **subsets** (API+core),
so the full-suite breakage in `tests/tools` was never observed. The plan §4
mandates the 5-surface scan + green gates before each landing commit; that
forcing function was not satisfied.

**Fix (junior, fix round):** re-wire `tests/tools/test_e2e.py` to authenticate
— create a user in `_make_ctx` and pass a bearer token (mirror the
`tests/api/conftest.py` `make_auth_headers`/`create_token` pattern), OR use a
shared authed-client helper. No product code change. Then re-run the **full**
`pytest` (not a subdir) to confirm green.

### F2 — 🟡 needs_architect: WS unauth-reject-before-`accept()` test absent (plan-mandated)

Plan P4.5-3 acceptance + P4.5-7 guard #2 + the absorbed **A-1/M3** all
explicitly require: *"an unauthenticated WS upgrade is rejected before
`accept()` (no stream frame ever sent — **assert no `accept()` on the unauth
path**)."* The **product code is correct** (`app.py` `_room_stream` validates
cookie/query-token/Bearer and `await websocket.close(code=1008)` **before**
`accept()`), but **no test pins it**: all 11 `websocket_connect` call-sites use
the authenticated `client` fixture; there is no unauthenticated-WS-reject test
and no assertion that `accept()` is not called on the unauth path. The mandated
guard #2 is implemented for the 7 HTTP routes only; its WS half is missing.

This is a plan→impl drift on an explicit acceptance criterion (the production
boundary holds, but the test-pinned guard the plan required is absent). Surfaced
for architect routing — recommend it be added in the F1 fix round (cheap: one
`unauth_client.websocket_connect(...)` expecting `WebSocketDisconnect`/close
1008).

### F3 — 🟡 flaky: `test_two_concurrent_subscribers_both_see_replay` non-deterministic (1/3 fail)

In isolation: **1 failed / 2 passed** over 3 runs; the failure is a ~6.5 s
timeout (vs ~1.1 s on pass), i.e. a timing race in the two-subscriber
subscribe-then-replay path, not a hard auth error. P4.5-3 added a per-WS-handshake
`validate_token` round-trip on the **reader executor** to this exact path
(`make_auth_headers` + the in-handler pre-`accept()` check), which adds latency
that **plausibly widens** a pre-existing race window. Needs characterization /
stabilization (e.g. bound the drain wait, or assert on union-of-both-results).
Flagged, not diagnosed-to-root — stabilization is a junior task once F1 lands.

### 🟢 Nits (non-blocking, no action required for verdict)

1. `tests/api/test_intent.py:396` docstring still reads *"the streamed event has
   author='user'"* but the assertion was correctly updated to
   `f"user:{TEST_USER_ID}"` (CLASS A). Stale docstring only.
2. `app.py` `_room_stream`: `loop = asyncio.get_running_loop()` is assigned
   twice (once in the new auth block, once after `accept()`). Harmless redundancy.
3. The P4.5-4 commit-message CLASS A list omits the `test_intent.py` streamed-
   author line it (correctly) changed. Bookkeeping only.

---

## Gate evidence

```
ruff check src tests           → All checks passed!
uv run mypy                     → Success: no issues found in 275 source files
uv run pytest (full suite)      → FAIL:
   FAILED tests/tools/test_e2e.py::test_e2e_local_auto_tool_appends_tool_result
   FAILED tests/tools/test_e2e.py::test_e2e_mcp_auto_tool_appends_tool_result_and_observation
   FAILED tests/tools/test_e2e.py::test_e2e_hard_mcp_tool_not_executed
   FAILED tests/tools/test_e2e.py::test_e2e_apply_edit_confirm_actuates
   FAILED tests/api/test_concurrency.py::...::test_two_concurrent_subscribers_both_see_replay  (flaky, see F3)
```
(An unrelated `tests/tools/test_net_trust.py` DNS-timeout *thread-exception
warning* — `hung.example.invalid` 5 s resolve — is environmental, not a counted
failure and not P4.5-related.)

---

## Verdict & expected routing

**blocking** — the impl is faithful to the plan's design on all 8 atomics, but
ships a red canonical pytest gate from a P4.5-introduced regression (F1) plus a
plan-mandated test omission (F2). Per dispatch I route nothing; architect routes.

Recommended fix round (junior, no product-code change): (1) **F1** re-wire
`tests/tools/test_e2e.py` to authenticate → full suite green; (2) **F2** add the
WS unauth-reject-before-`accept()` test; (3) **F3** stabilize the flaky
concurrent-subscribers test. Then re-run ruff + mypy + **full** pytest.

---

## Round 2 — verdict-bump re-review (RC-10), 2026-06-06

**Trigger:** junior reworked all three round-1 findings on `claude/P4.5-impl`.
Per RC-10 I re-read the rework diffs and **re-ran the CANONICAL gates myself**
(ruff + `uv run mypy` files=src,tests + **full** `pytest`, no subdir) — the
full-suite run is exactly what surfaced F1 in round 1, so I did not shortcut it.

**Rework commits verified:**

| Finding | Round-1 verdict | Rework | Evidence (re-verified) |
|---|---|---|---|
| **F1** | 🔴 blocking | RW1 `7009f2f` | `tests/tools/test_e2e.py` now builds an authed client: `_make_authed_client` creates a real user (`init_auth_schema`+`create_user`) and attaches a `create_token` Bearer header; all 4 previously-401'd e2e tests pass under the **full** suite. Pure test change, no product code. ✅ |
| **F2** | 🟡 needs_architect | RW2 `1cf34f9` | Guard #2's WS half now pinned: `test_ws_unauthenticated_rejected_with_1008` asserts `WebSocketDisconnect` with `code == 1008` on the `unauth_client` (close **before** `accept()`). Bonus `TestLensACookiePath` integration test pins the D3 cookie path. `unauth_client` fixture confirmed at `tests/api/auth/test_constitution.py:126`. ✅ |
| **F3** | 🟡 flaky | RW5 `5add58b` | Unbounded `_drain_until_replay_complete` replaced by a bounded drain (`len(pre)+10` iterations) in `test_two_concurrent_subscribers_both_see_replay`; test passed in the full run. ✅ |

**Adjacent rework observed (not my findings — R0-A-routed hardening):** RW3
`adf7053` (tighten middleware + make `/logout` auth-required), RW4 `f114522`
(`_post_intent` assert principal is not None — fail-closed), RW5b `ca8ca1c`
(ruff fix). These strengthen the fail-closed boundary and are **consistent with
the plan's design intent** (no plan-faithfulness regression); they fall under the
R0-A lens, not plan-vs-impl, and are covered by the green gates I re-ran.

**Round-2 gate evidence (senior re-run):**

```
ruff check src tests           → All checks passed!
uv run mypy                     → Success: no issues found in 275 source files
uv run pytest (full suite)      → exit 0, 100%, 2221 passed, 0 failed/errored
```
(The `tests/tools/test_net_trust.py` `hung.example.invalid` DNS-timeout thread-
exception *warning* persists — environmental, not a counted failure, not
P4.5-related; same disposition as round 1.)

**Round-2 verdict: `clean`.** All three round-1 findings resolved; the impl
remains faithful to the plan on all 8 atomics and now ships green canonical
gates. Per dispatch I route nothing; expected state-machine auto-advance →
`awaiting_R0_A` (ADR-008 Amendment 1, Route B) once R0-A verdict is likewise
clean.
