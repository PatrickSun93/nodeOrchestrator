---
task_id: P4.5
review: plan-vs-impl
reviewer: senior planner
date: 2026-06-06
plan: docs/process/senior-plans/P4.5.md
impl_branch: claude/P4.5-impl
impl_commits: [4e34c7b, 21eb0be, 40f7d2a, 5b2729f, 8a0e1ec, bbafa86, a07a932, 7924b36]
verdict: blocking
findings_count: { red: 1, yellow: 2, green: 3 }
gates:
  ruff: pass
  mypy: pass            # Success: no issues found in 275 source files
  pytest: FAIL          # 4 hard P4.5-introduced regressions in tests/tools/test_e2e.py + 1 flaky
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
