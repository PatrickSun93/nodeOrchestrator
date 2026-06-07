---
task_id: P4.5
round: R0-A
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 7
verdict_history:
  - round: 1
    impl_head: 7924b36
    verdict: needs_architect
    summary: "0🔴 4🟡 7🟢 @ 7924b36. Y1-impl (/logout public + _is_public /health-prefix → unauthenticated writer-revoke), Y2 (_post_intent else 'user' fail-open), Y3 (cookie-path + WS-negative coverage gaps), Y4 (verify-timing / idle-expiry / token-hash docstring honesty). Boundary fail-closed, constitutional spine byte-frozen, plan-stage Y1 wiring seam resolved. Route nothing — surfaced for architect."
  - round: 2
    impl_head: ca8ca1c
    verdict: needs_architect
    summary: "All 4 round-1🟡 RESOLVED (architect-routed α; junior RW2–RW5b): Y1-impl→RW3 adf7053, Y2→RW4 f114522, Y3→RW2 1cf34f9, Y4→RW5 5add58b — verified by diff + code read; product code fail-closed; spine intact (scoring.py byte-frozen, core/event.py untouched in rework). Gates re-run by me: ruff ✅ / mypy ✅ (275 files) / pytest ❌ NOT clean. NEW 🟡 Y5: RW5(d)'s flaky-test 'stabilisation' is INEFFECTIVE — tests/api/test_concurrency.py two_concurrent_subscribers_both_see_replay still flakes (assert 0==3, replays 0/3 events) AND hangs (reproduced >6 min); the bounded loop caps iteration count but ws.receive_json() has no timeout, the two threads share one reader_store.conn, and the worker threads are non-daemon → a stuck thread deadlocks the pytest process → CI hang (the recurring multi-day stale-pytest zombies are this). Pre-existing P2.x WS-replay raciness, NOT a P4.5 regression, but a CI-deadlocking hang R0-A must not pass. Architect-routed α (junior truly fixes the hang, no revert) → RW6. Two below-bar residuals noted (noting-not-blocking): (a) verify_password disabled-branch returns pre-scrypt — weaker oracle than the fixed not-found path; (b) authenticated-/logout success path / revoke_sessions_for_user has no positive test. Verdict stays needs_architect — cannot clean until the hang is fixed and the full suite is stably green (round-3)."
  - round: 3
    impl_head: bb8f47a
    verdict: needs_architect
    summary: "RW6 (bb8f47a) ELIMINATED the Y5 CI-deadlock hang — verified by me: target test 15/15 PASS no hang, targeted scope exit 0, full pytest exit 0 (0 failed; lone warning = unrelated test_net_trust hung-DNS daemon thread), ruff+mypy(275) green. RW6 = (a) conftest reader_exec max_workers 2→1, (b) _room_stream auth try/except→close(1011) before accept, (c) test threads daemon=True. BUT it fixed the SYMPTOM not the true root cause → NEW 🟡 Y6: production app.py:276 reader_executor=ThreadPoolExecutor(max_workers=4) shares ONE reader_conn (app.py:272) — the exact concurrent-single-SQLite-connection race junior diagnosed; RW6 changed only the TEST fixture (a) + a WS-auth-only close-guard (b, doesn't cover replay app.py:947 / GET reader paths), so production still races on concurrent reads. P4.5's multi-user seam (DP1=b) makes concurrent reads the NORMAL condition (2 users ⇒ correctness, not F-scale). RW6 commit's '(a) no SQLite race (root cause)' overstates (test-only); test-green fidelity dropped (max_workers=1 serialises the very concurrency it tests while prod=4); writer is correctly max_workers=1 (ADR-025 D6) — reader=4 on a shared conn is the asymmetry bug. Architect ruled concurrent-reader on the multi-user path is P4.5 IN-SCOPE → routed α-RW7 (per-thread/thread-local reader conn, keep writer single-conn, make test truly concurrent, fix wording). Y1-Y4 still resolved (untouched by RW6); L3 reject-before-accept + Y3 1008 test still hold (new 1011 path also pre-accept). 2 below-bar residuals persist. Verdict needs_architect — not clean until true root cause (Y6) fixed + suite stably green (round-4)."
  - round: 4
    impl_head: d2b5566
    verdict: needs_architect
    summary: "RW7 (d2b5566) TRULY fixed Y6 — verified by me: per-thread WAL reader pool (reader_executor initializer=_init_reader_worker + threading.local; every reader lambda resolves get_reader_conn()/get_reader_store() at RUN-TIME on its own worker thread — RW6's bug was capturing one conn on the loop thread; WAL set on writer app.py:290 is DB-file-level so all per-thread reader conns inherit it) eliminates the shared-connection race. Target test 15/15 PASS under the now genuinely-concurrent config (conftest upgraded to max_workers=4 + per-thread initializer → fidelity restored; test now asserts not-alive 'reader hang?', no longer daemon-masked); full pytest exit 0, 0 failed; ruff 0 / mypy 275. Writer untouched (single conn, max_workers=1 — ADR-025 D6 two-connection-model semantics intact). RW6's overstated wording corrected (conftest comment removed; RW7 commit acknowledges RW6 masked it). Y1-Y4 still resolved (RW7 only touched reader paths + executor config). NEW 🟡 Y7 (ADR-as-contract integrity): the per-thread reader pool contradicts the single-reader-connection model inscribed in ADR-039 (line 19 'a separate read-only WAL reader connection'; line 137 'the reader connection') AND ADR-025 D6 (line 80 singular; line 99 Considered-Alternatives 'a thread pool of connections — Rejected for MVP, pooling is a perf forward hook (WAL)') — neither updated, so ADR-039 (Accepted this cycle) mis-describes its own impl. Architect ruled α (inscribe-first): senior updates ADR-039 (line 19/137 → per-thread WAL reader pool) + annotates ADR-025 D6 (the deferred pooling forward-hook is now ACTIVATED; rationale = P4.5 multi-user concurrent-read correctness; writer single-conn unchanged); then round-5 verifies impl↔ADR consistency → clean. 2 below-bar residuals persist (verify_password disabled-branch pre-scrypt; authenticated-/logout positive path untested). Verdict needs_architect — not clean until the ADR reader-model inscription lands (round-5)."
  - round: 5
    impl_head: d3faf50
    verdict: needs_architect
    summary: "Senior inscribed the per-thread reader model (d3faf50: ADR-039 line 19/52/137 + ADR-025 D6 annotation) — accurate for routes + WS. BUT tracing the inscription's 'validated on the per-thread WAL reader pool' claim against the impl exposed that RW7's per-thread fix was INCOMPLETE → NEW 🟡 Y8: the HTTP auth middleware (src/orchestrator/api/auth/middleware.py) was NEVER touched by RW7 (its file-set = app.py + conftest + test_concurrency) and still captures the SHARED ctx.reader_store.conn (middleware.py:85) then runs validate_session/validate_token on it via the 4-worker reader_executor (middleware.py:92, :103) — the exact Y6 shared-connection race, in the HIGHEST-traffic auth path (_resolve_principal runs on every protected HTTP request). grep confirms middleware.py:85 is the ONLY remaining shared-conn reader usage in src/. EMPIRICALLY REPRODUCED by me (40 concurrent authed HTTP reqs → 30×404 OK + 6×spurious-401 [valid bearer token rejected] + 4×InterfaceError 'bad parameter or other API misuse' [SQLite concurrent-single-conn corruption]). Fail-closed (reject/500, never grant — NO auth bypass) but a real multi-user correctness/availability bug (P4.5's core path rejects legitimate users under concurrency) + makes d3faf50's ADR-039 line 52/137 inaccurate for the HTTP path (HR#5). Uncaught earlier: round-4 grepped app.py not auth/middleware.py (my miss); the suite is green because no test exercises concurrent HTTP-through-middleware (the concurrency test is WS-replay-only). Architect routed α-RW8: apply RW7's _room_stream pattern to middleware.py — drop the reader_conn=ctx.reader_store.conn capture (line 85), resolve ctx.get_reader_conn() INSIDE each lambda (lines 92, 103) at run-time on the worker thread + add a concurrent-HTTP-auth regression test; then middleware is the last shared-conn site migrated, the inscription becomes accurate → round-6 clean. Y1-Y4 + Y6 (routes/WS) + Y7 (inscription written) still hold; 2 below-bar residuals persist. Verdict needs_architect — not clean until RW8 migrates the middleware + the regression test lands (round-6)."
reviewer: architect-partner
date: 2026-06-06
reviewed_artifacts:
  - src/orchestrator/api/auth/{principal,users,session,middleware,__init__}.py
  - src/orchestrator/api/{app,admin,__main__}.py
  - src/orchestrator/core/event.py
  - src/orchestrator/autonomy/scoring.py (byte-frozen check)
  - src/orchestrator/api/wire.py
  - tests/api/{conftest,test_intent,test_confirm}.py + tests/api/auth/*
contract:
  - docs/decisions/ADR-039-auth-identity-model.md (Accepted 2026-06-06)
  - docs/process/senior-plans/P4.5.md
against: claude/P4.5-impl @ 7924b36 (8 atomic commits over origin/main)
gates: ruff ✅ · mypy ✅ (275 files) · pytest — suite GREEN but a COVERAGE GAP hid Y8 (no concurrent-HTTP-auth test; the concurrency test is WS-replay-only). Y8 EMPIRICALLY reproduced by me out-of-suite — 40 concurrent authed reqs → 6 spurious-401 + 4 InterfaceError. verdict needs_architect on Y8 (middleware shared-conn race — see verdict_history R5 + Round 5 §). [history — R4 Y7 inscription; R3 Y6 code-fixed by RW7; R2 Y5 hang fixed by RW6; R1 373✅]
---

# R0-A on impl — P4.5: the first human-identity trust boundary (ADR-039 D1–D10)

**Dispatch:** architect-partner R0-A of the real impl code (8 atomic, `claude/P4.5-impl`), running the seven dispatch lenses against ADR-039 D1–D10 + the five Hard-requirements to confirm they are **truly landed** (not just plan-promised). Verify-cited `file:line` against the impl tree. **Route nothing** — findings surfaced for architect routing; I do not decide α/β/γ.

**NOT relitigated** (architect-ratified `9356bea`, checked only for *honoring*): DP1b real-multi-user seam, DP3a all-or-nothing operator, DP2 five-things scope, D2/MCP-OAuth deferral, TLS-at-proxy, SameSite=Strict same-origin (A-2).

**Verdict: `needs_architect`.** The boundary is correctly **fail-closed**, the constitutional spine is **preserved byte-for-byte**, and the plan-stage **Y1 (the wiring seam) is now genuinely resolved** — the shipped middleware is exercised by the whole suite, not a test-only shim. **0🔴.** Four 🟡 are hardening / honest-residual / coverage decisions (all below the do-not-reverse bar; none breaks an HR), each with a lean for routing.

---

## Headline: the plan-stage Y1 is resolved in impl (the security crux)

The plan-stage 🟡 was *"will the fail-closed middleware be wired so the test-suite exercises the **shipped** boundary, not a test-only path?"* **Confirmed resolved:**

- A single construction-time `_configure(app)` (`app.py:976-989`) registers `AuthMiddleware`, and it is called by **both** factories — `create_app` (`app.py:1016`) and `_make_test_app` (`app.py:1023`).
- `ctx` is stowed on `app.state.ctx` — in lifespan for prod (`app.py:1005`) and directly in the test factory (`app.py:1025`); the middleware reads `request.app.state.ctx` at request time (`middleware.py:80`), with `ctx is None → return None →` fail-closed `401` (`middleware.py:81-82`).
- The 37→373 API tests build via `_make_test_app` and authenticate through the live middleware (`conftest.py:113-129`, Bearer token). Guard #12 (`test_constitution.py:504-525`) asserts behaviorally that an unauthenticated request to the **test** app gets `401`; Guard #13 (`:528-547`) asserts the authed path stamps `user:<id>`. **tested-app == shipped-app at the auth crux** — the Y1 failure mode (boundary exercised by zero tests) does not occur.

---

## Lens confirmations (the seven dispatch lenses — verified against impl)

**L1 — principal server-derived; wire bodies carry no identity field (forge-guard generalised).** `IntentRequest` (`wire.py:48-60`, `extra="forbid"`) and `ConfirmRequest` (`wire.py:121-131`, `extra="forbid"`) carry no `author`/`id`/`user_id`/`approver_user_id` — identity on the wire is type-impossible. `_post_intent` stamps `author = build_user_author(principal.user_id)` from `request.state.principal` set by the middleware (`app.py:554-563`), never the body; `build_user_author` raises on empty (`event.py:449-458`). Forge tests assert `author`/`id`/`timestamp`/`agent_id`/`user_id` → 422 (`test_intent.py:102-133`, `test_constitution.py:139-189`). **Honored** (see Y2 for the `else "user"` fallback nuance).

**L2 — fail-closed-on-unauthenticated.** Middleware returns `401` **before** `call_next` (`middleware.py:57-70`) — i.e. before any handler / append / `run_turn`. Public allowlist is explicit (`middleware.py:35-39`); default is closed. Parametrized `401` across all 7 protected routes (`test_constitution.py:195-213`) + a fail-closed-**by-default** test (a new dummy route is `401` without being allow-listed, `:215-229`). **Honored** (see Y1-impl for the allowlist *contents*).

**L3 — WS reject BEFORE `accept()`.** `_room_stream` resolves the principal from cookie / `?token` / `Authorization` (`app.py:892-922`) and, on `None`, `await websocket.close(code=1008); return` (`app.py:924-927`) — strictly before `websocket.accept()` (`app.py:932`). No half-open-stream window. The positive path is exercised transitively (the e2e WS tests pass through it with the authed client). **Honored** (negative-path test gap → Y3).

**L4 — gate stays identity-blind; spine byte-frozen.** `Operation` carries no actor field (`scoring.py:19-33`, `extra="forbid"`); `scoring.py` is **absent from the diff** (`9772720..HEAD`) — `score`/`decide_tier`/`gate` byte-unchanged. Guard #7 freezes the exact field set `{tool_id, initiating_agent, user_explicit_intent, params, estimated_cost_usd}` (`test_constitution.py:337-345`); Guard #8 greps the auth module for `LLMPurpose` (none, `:348-358`). **Honored — clean.**

**L5 — confirm provenance is a nullable field on the EXISTING metadata; TOOL_CALL stays agent-authored; idempotency untouched.** `approver_user_id: str | None = None` added to `ToolCallMeta` (`event.py:218`) and `ToolCallCancelledMeta` (`event.py:380`) — **no new event type**; `PENDING_RESOLUTION_TYPES` (`event.py:401-408`) and `TYPED_METADATA` (`:383-397`) unchanged. The approve path stamps `author=build_author(pending_meta.initiating_agent)` (`app.py:788`) + `approver_user_id` from the principal (`:795`); cancel likewise (`:763/:768`). The still-pending scan keys on `type ∈ PENDING_RESOLUTION_TYPES` + `call_id` and **never inspects `approver_user_id`** (`app.py:747-751`) — so the additive field cannot touch idempotency. Guard #10 asserts TOOL_CALL is `agent:coordinator` *and* `metadata.approver_user_id == testuser` (`test_constitution.py:457-501`); the full ADR-030 invariant suite (double-approve, cancel, room-state, cross-turn collision, writer atomicity, execute-stage durability) regression-passes through auth (`test_confirm.py`). **Honored — clean.**

**L6 — RB-AUTHZ residual honest; checkpoint seams pinned.** D5 seam #1 (confirm-approve) is marked in-code: *"D5 checkpoint seam #1: authenticated ⇒ allowed; role check would gate here"* (`app.py:707`). Seams #2 (plugin-admit) and #3 (config-write/user-create) correctly have **no endpoint code** — pinned in ADR-038's P4.5-8 annotation and ADR-039 D5/D9; the bootstrap test confirms no unauthenticated user-create route exists (`test_constitution.py:303-309`). `RB-AUTHZ` is inscribed (ADR-039 D10 + ADR-038 annotation). **Honored** (residual-honesty nits → Y4).

**L7 — credential storage + bootstrap + remote-bind.** `scrypt` (n=2¹⁴/r=8/p=1) + per-user `os.urandom(16)` salt + `hmac.compare_digest` (`users.py:89-119`); the hash/salt never escape — `User` has no credential field, `verify_password` returns `bool`, both `del` the locals (`users.py:75-81/127-199`). Bootstrap is the out-of-band admin CLI (`admin.py`). Remote-bind guard: `_is_loopback` uses `ipaddress.is_loopback` + literal `localhost` (covers 127.0.0.0/8 + ::1, rejects 0.0.0.0/::; `__main__.py:38-50`), refusing a non-loopback bind with zero provisioned users at startup (`:53-91`). Thoroughly tested (`test_users.py`, `test_remote_bind.py`, Guard #4/#5). **Honored** (timing/idle-expiry nits → Y4).

**ADR annotations (P4.5-8).** ADR-025 (D4 author-from-principal / D7 localhost→authenticated), ADR-026 (GUI carries cookie, still decides nothing), ADR-030 (**N1 hook LANDED** — the nullable `approver_user_id`), ADR-038 (D5 authz dimension pinned) — all substantive and accurate. **Honored.**

---

## Findings (4🟡 — all needs_architect routing; none blocking)

### 🟡 Y1-impl — the public allowlist is wider than the ADR's `{login, health, bootstrap}` (HR#2 scope)

`PUBLIC_PATHS = {/login, /logout, /health}` (`middleware.py:35-39`), and `_is_public` additionally prefix-matches `path.startswith("/health")` (`:42-43`). HR#2 / D4 pin the allowlist as *"login + bootstrap + health … explicit and minimal."* Two deltas:
1. **`/logout` is public.** Its handler does a **writer-executor `revoke_session`** reachable unauthenticated (`app.py:443-456`) — an anonymous client can spend writer-executor turns (the single `max_workers=1` writer also serves `/intent`·`/confirm`·`run_turn`) and revoke any session whose opaque id it presents in its own cookie. Practically low-risk (ids are 32-byte random; SameSite=Strict blocks cross-site forced-logout), but it widens a constitutionally-pinned set and adds an unauthenticated write path.
2. **`startswith("/health")`** makes `/health*` (e.g. a future `/health-admin`) public by prefix — broader than the exact entry, against fail-closed-by-default hygiene.

**Lean α (cheap):** move `/logout` behind auth (you must be authenticated to log out — the natural case; logout then revokes the *current* principal's session) and switch the health check to exact-match. **Or** architect ratifies the widened allowlist + the unauthenticated-revoke surface. This is HR#2 allowlist scope → architect's call, not mine.

### 🟡 Y2 — the `_post_intent` author fallback `else "user"` is a latent fail-open seam at the forge guard

`_author = build_user_author(_principal.user_id) if _principal is not None else "user"` (`app.py:554-557`). In any correctly-wired app the branch is **unreachable** (the middleware 401s before the handler runs, so `request.state.principal` is always set) and **no test relies on it** (all authenticate and assert `user:<id>`). But it means the handler does **not** itself assert the invariant — it silently degrades to the legacy `"user"` author if the principal is ever absent, fail-**open** at the exact site D7 calls the security crux. Contrast `_post_confirm`'s `else None` (`app.py:713-715`), which is **by-design** (D6 makes `approver_user_id` nullable) and is *not* a finding.

**Lean α (cheap):** assert `principal is not None` (raise 500) instead of falling back — makes the middleware↔handler invariant explicit and fail-closed end-to-end. **Or** accept + add a one-line comment that the branch is middleware-guaranteed-unreachable.

### 🟡 Y3 — auth-path test coverage gaps at the GUI's primary path + the WS reject-before-accept

The token branch is integration-tested everywhere; two security-critical branches are **not** driven end-to-end through the wiring:
- **Cookie branch** (`middleware.py:88-95`) — the GUI's *primary* path. Only `validate_session` is unit-tested (`test_sessions.py`); no test drives `/login → Set-Cookie → authed request` through the middleware. `conftest.py:122` deliberately uses a token to dodge the Secure-cookie-over-HTTP `TestClient` issue — reasonable, but it leaves the cookie→principal→handler path without integration coverage. (Workaround: `TestClient(base_url="https://testserver")` or a manually-set cookie.)
- **WS reject-before-accept negative path** (`app.py:924-927`) — the A-1 security property. The positive path is covered transitively; no test asserts an **unauthenticated** WS upgrade is closed *before* `accept()`.

**Lean α/β:** add a cookie-path integration test + a WS-unauth-rejected test (α, small), or defer with the gap named (β). Code looks correct; this is coverage, not a correctness defect.

### 🟡 Y4 — residual-honesty nits (HR#5)

Three small gaps between the ADR's promised posture and the impl/comments — HR#5 asks residuals read *honestly*:
1. **`verify_password` user-enumeration timing.** On user-not-found it returns `False` **without** running `scrypt` (`users.py:188-193`), while found-user-wrong-password runs scrypt — a timing oracle for username enumeration. The docstring claims *"timing leak is minimised even on miss (the scrypt call runs regardless when the row exists)"* (`users.py:182-184`) — inaccurate for the not-found path. Fix: dummy-scrypt on miss, **or** correct the docstring + name it in D10 credential-posture.
2. **Session idle-expiry not built.** D3 promises *"a TTL + idle expiry"*; the impl has only an absolute 24h TTL (`session.py:43-44/106-123`), no sliding/idle window. Either build it or add it to the D10 residual.
3. **Token hash docstring.** `session.py:9` says the bearer token is *"stored hashed (same scrypt discipline)"* but it uses SHA-256 (`session.py:52-53/138-139`). SHA-256 on a 256-bit random token is **correct** (the inline note at `:46-49` justifies it well) — only the module docstring is misleading.

**Lean α:** doc/comment fixes + the dummy-scrypt are all small; idle-expiry is the only real build, plausibly β (name as residual).

---

## Green notes (no action required)

- **G1** Principal model carries only `user_id` (`principal.py:13-21`), dropping the ADR's parenthetical *"+ carried session/token provenance"* — harmless; the provenance is not load-bearing for any invariant.
- **G2** Two-connection discipline honored: sessions created/revoked on the writer, validated on the reader (`session.py:76-123`, `middleware.py:84-93`) — ADR-025 D6 liveness preserved; Guard #11 asserts reader-side validate.
- **G3** `init_auth_schema` is idempotent (`IF NOT EXISTS`) and co-located in the main DB (`users.py:58-67`) — matches the storage idiom; called from `_build_context` (`app.py:266-269`) and both test ctx fixtures.
- **G4** `_LoginRequest` is `extra="forbid"` (`app.py:132-138`) — the `/login` body legitimately carries `{user_id, password}` (credential presentation, server-verified before trust) and is **not** a forge vector (D7).
- **G5** Cookie attributes correct: `HttpOnly + Secure + SameSite=Strict`, `max_age=86400` (`app.py:432-440`) — matches D3 same-origin posture.
- **G6** `create_user` maps `IntegrityError → ValueError` for duplicates (`users.py:155-156`); `user_id` regex enforced (`:138-139`).
- **G7** Gates green (run by me): ruff exit 0; mypy "no issues, 275 files"; pytest tests/api+tests/core 373 passed (exit 0).

---

**Routing summary for the architect (I decide nothing — leans only):**

| # | Finding | Lean | Bar |
|---|---|---|---|
| Y1-impl | `/logout` (+`/health*`) in public allowlist; unauthenticated writer-revoke | α (move behind auth + exact-match) **or** ratify | HR#2 scope |
| Y2 | `_post_intent` `else "user"` fail-open fallback | α (assert) **or** accept+comment | hardening |
| Y3 | cookie-path + WS-negative integration coverage | α (add 2 tests) **or** β (name gap) | coverage |
| Y4 | verify-timing docstring · idle-expiry · token-hash docstring | α (doc/dummy-scrypt) + β (idle-expiry residual) | HR#5 honesty |

The boundary is sound and fail-closed; the spine is intact; Y1-from-plan is resolved. None of the above is do-not-reverse or HR-breaking.

---

## Round 2 — verdict-bump re-review (RC-10): four 🟡 resolved, NEW Y5 blocks clean

**Dispatch.** Architect routed all four round-1 🟡 as α; junior reworked (RW1–RW5b on `claude/P4.5-impl @ ca8ca1c`). This is the RC-10 verdict-bump re-verification: confirm each routed 🟡 is genuinely resolved, the product-code changes are correct, no constitutional invariant regressed, and re-run the gates. **Route nothing** — the one new finding (Y5) was architect-routed α in-chat; recorded below.

**Verdict: `needs_architect` (cannot bump to clean).** All four round-1 🟡 are resolved and the auth boundary is sound, but re-running the gates surfaced a CI-deadlocking hang in a test RW5 bundled-and-claimed-to-stabilise (**Y5**). The hang must be fixed before clean (→ round-3).

### The four round-1 🟡 — all resolved

| Round-1 🟡 | Rework | Verified resolved |
|---|---|---|
| **Y1-impl** — `/logout` public + `_is_public` `startswith("/health")`; unauthenticated writer-`revoke_session` | RW3 `adf7053` | `_is_public` is now `path in PUBLIC_PATHS` (exact); `PUBLIC_PATHS = {/login, /health}`. `/logout` is protected — added to the parametrised-401 `PROTECTED_ROUTES` (`test_constitution.py:203`). `_logout` reads `request.state.principal` (middleware-guaranteed) → new `revoke_sessions_for_user(conn, principal.user_id)`: revocation is driven by the *authenticated* principal, never an attacker-presented cookie; the unauthenticated write path is closed. No real `/health*` sub-route exists in `src/` (only the allowlist entry) → exact-match drops zero coverage. |
| **Y2** — `_post_intent` `else "user"` fail-open fallback | RW4 `f114522` | Replaced with `assert _principal is not None` → `build_user_author(principal.user_id)`. Fail-closed (AssertionError → 500); *strengthens* L1 (author server-derived). Robust even under `python -O` (assert stripped): the next line dereferences `principal.user_id` → AttributeError → 500. `_post_confirm`'s by-design `else None` (D6 nullable approver) correctly left untouched. |
| **Y3** — cookie-path + WS-reject-before-accept coverage | RW2 `1cf34f9` | `TestLensACookiePath` drives `/login → Set-Cookie → cookie-authed POST /rooms` through the live middleware (`TestClient(base_url="https://testserver")` so the Secure cookie is sent). `test_ws_unauthenticated_rejected_with_1008` asserts `WebSocketDisconnect(1008)` is raised on context-*enter* — only true if the server closes *before* `accept()` (the A-1 property). |
| **Y4** — verify-timing / idle-expiry / token-hash docstring honesty | RW5 `5add58b` | (1) `verify_password` runs a dummy `hashlib.scrypt` on the not-found path with identical `n/r/p` → closes the user-existence timing oracle; docstring corrected. (2) `session.py` module docstring corrected: bearer token is SHA-256 (correct for a 256-bit-entropy token), not scrypt. (3) ADR-039 D10 names two honest residuals — bearer-token-no-expiry, session-no-idle-expiry — as architect-ratified not-built. |

Product code is fail-closed and the constitutional spine is intact: `scoring.py` is byte-frozen and `core/event.py` shows no diff in `7924b36..HEAD`; the Y2 change only *tightens* the server-derived-author invariant.

### 🟡 Y5 (round-2, NEW) — RW5(d)'s flaky-test "stabilisation" is ineffective; the concurrency test deadlocks CI → **architect-routed α (junior fix, no revert)**

`tests/api/test_concurrency.py::TestMultipleConnections::test_two_concurrent_subscribers_both_see_replay` exhibits **three** modes when I re-ran the gates:
- **pass** (isolation run 1);
- **fail** — `assert 0 == 3`: both concurrent subscribers replay **0** of the 3 pre-appended events (full targeted-scope run);
- **hang** — isolation run 2 blocked **>6 min** before I killed it.

RW5(d)'s commit claims the bounded drain (`range(len(pre)+10)`) "prevent[s] infinite hang." It does **not**: the bound caps *iteration count*, but `ws.receive_json()` (`test_concurrency.py:137`) has **no timeout**, so a single blocking call still hangs forever; and the worker threads are **non-daemon** (`:146`), so one stuck thread blocks the pytest process from exiting → the full suite deadlocks in CI. (The ~30 multi-day stale `pytest` zombies across sessions — several running this exact test — are this hang recurring.)

**Root cause** (pre-existing, P2.x pubsub / WS-replay — **not** a P4.5 regression): both threads' replays read historical events from the **same shared `reader_store.conn`** (one SQLite connection), so concurrent cursors race → 0 rows / block. Each test is DB-isolated (`tmp_path`), so this is intrinsic raciness, not cross-process contention. P4.5's auth slice never touched the replay / reader-conn path; RW5 only altered the drain bounding.

**Why this blocks clean (despite being test-only + pre-existing):** a CI-deadlocking hang that a rework commit *claims to have fixed but hasn't* is exactly what R0-A must not pass. **Architect routing (given in-chat): α — junior truly fixes the hang (RW6), no revert.** The fix is small: give `receive_json` a real timeout (and/or make the worker threads daemon, and/or fix the shared-reader-conn race). Clean awaits round-3: hang fixed + full suite stably green.

**Cross-lens note.** Senior plan-vs-impl round-2 (`932f25b`) and R0-B round-2 (`51e2e57`) both judged `clean` and read RW5(d) as having "stabilised" the test; the senior's *single* full-suite run passed (2221), consistent with this test's flaky nature. The nondeterministic flake/hang only surfaces on **re-run** — which is how this lens caught it. The divergence is reconciled by the architect's α routing (fix the hang before P4.5 closes).

### Below-bar residuals (noting, not blocking — no routing)

- **`verify_password` disabled-user branch** (`users.py:201-202`) returns before scrypt, so a *disabled* account stays timing-distinguishable — a strictly weaker oracle than the not-found existence-enum Y4 fixed (it requires the account to exist *and* be disabled), and outside Y4's scope. Optional follow-on: run the dummy-scrypt on the disabled branch too.
- **Authenticated-`/logout` success path** (`_logout` + `revoke_sessions_for_user`) has no positive integration test — only the unauthenticated-401 case is covered. The function is a single parametrised `UPDATE` mirroring `revoke_session`, and the security-relevant property (route is protected) *is* tested; the success path is a minor coverage gap, not a correctness defect.

### Gates (round-2, re-run by me)

- **ruff** ✅ exit 0
- **mypy** ✅ "no issues found in 275 source files" (`files=src,tests`)
- **pytest** ❌ **not clean** — `tests/api + tests/core + tests/tools/test_e2e.py`: all green **except** Y5's concurrency test (flake/hang). The full-suite-green (2220 passed) reported by the junior + senior runs reflects the test's *flaky* nature (it usually passes), not stability.

---

## Round 3 — verdict-bump re-review (RC-10): Y5 hang eliminated, deeper root cause Y6 found → architect-routed α-RW7

**Dispatch.** Junior pushed RW6 (`bb8f47a`) to truly fix the Y5 hang. RC-10 re-verification: confirm the hang is gone + suite stably green + Y1–Y4 still resolved, and trace whether the fix addresses the real cause. **Route nothing** — the deeper finding (Y6) was architect-routed α in-chat; recorded below.

**Verdict: `needs_architect` (still cannot clean).** The Y5 CI-deadlock **hang is genuinely eliminated**, but tracing RW6 shows it fixed the *symptom* (the test no longer hangs) without fixing the *true root cause* — a production concurrent-reader SQLite-connection race (**Y6**). The architect ruled this is P4.5 in-scope (the multi-user path) → α-RW7, not an F-scale inscribe-defer.

### Verification (re-run by me, round 3) — all green

- **target test** `test_two_concurrent_subscribers_both_see_replay` — **15/15 PASS, zero hangs** (each run `timeout 60`-guarded)
- **targeted scope** `tests/api + tests/core + tests/tools/test_e2e.py` — exit 0
- **full pytest** — exit 0, 0 failed (the lone `PytestUnhandledThreadExceptionWarning` is `tests/tools/test_net_trust.py`'s `hung.example.invalid` daemon thread — unrelated to P4.5 / the reader path)
- **ruff** exit 0 · **mypy** "no issues, 275 files"
- **Y1–Y4** untouched by RW6 → still resolved. The new `_room_stream` exception path `close(1011)` is also **before** `accept()` (`app.py:923-927` vs `:937`), so L3 reject-before-accept and the Y3 `1008` unauth test still hold.

### RW6 (`bb8f47a`) — what it fixed, and what it didn't

| Part | Change | Effect |
|---|---|---|
| (a) | `conftest.py` reader_exec `max_workers 2→1` | Serialises the **test** reader → no race **in tests**. Root-cause-shaped, but **test-fixture only**. |
| (b) | `_room_stream` auth wrapped in try/except → `close(1011)` before accept | **WS-auth** path fails-closed instead of hanging. Does **not** cover replay (`app.py:947`) or the GET reader endpoints. |
| (c) | `test_concurrency.py` threads `daemon=True` | Test can't deadlock CI even if a thread stalls. Safety-belt. |

### 🟡 Y6 (round-3, NEW — the true root cause) — production reader executor shares one SQLite connection → **architect-routed α-RW7**

The hang's real cause is a **production** concurrency bug, not a test artefact:
- `app.py:272` opens a **single** `reader_conn`; `app.py:276` runs `reader_executor = ThreadPoolExecutor(max_workers=4)`. So up to 4 executor threads use the **same** SQLite connection concurrently — `check_same_thread=False` only suppresses the guard, it adds no thread-safety. This is the exact race the junior diagnosed (concurrent cursor ops corrupt connection state → `validate_*` raises → uncaught-before-accept → client blocks).
- RW6 fixed this only in the **test** fixture (a) and band-aided the **WS-auth** hang (b). Production still races on every concurrent read: replay (`app.py:947`), `GET /rooms`/events/thread, `/login` verify. Under concurrency these raise → `500` (replay/GET, unguarded) or a spurious `1011` (WS-auth, via (b)). All fail-closed (no hang, no security hole), but a real degradation.
- **Why P4.5-in-scope (architect ruling):** P4.5's purpose is the real multi-user seam (DP1=b). **Concurrent reads are the *normal* multi-user condition** — two simultaneous users trigger this. Two-user correctness ≠ F/scale; the architect ruled it in-scope rather than an inscribe-and-defer F-residual.
- **Honesty (HR#5):** RW6's commit "(a) … no SQLite race (root cause)" **overstates** — the race is fixed only in tests; prod is untouched. And the test's green fidelity dropped: `max_workers=1` serialises away the very concurrency the test is named for, while prod runs `4`.
- **Asymmetry:** the writer is correctly `max_workers=1` (single conn, serialised — ADR-025 D6). The reader being `max_workers=4` on a shared conn is the bug.

**Architect routing (in-chat): α — junior RW7** truly fixes it (per-thread / thread-local reader connection to remove the shared-connection race, keep the writer single-conn serialisation per ADR-025 D6, make the test *genuinely* concurrent to restore fidelity, and correct the RW6 wording). Clean awaits round-4: true root cause fixed + suite stably green.

### Below-bar residuals (still noting, not blocking)

- **`verify_password` disabled-user branch** (`users.py:201-202`) returns before scrypt — a weaker oracle than the not-found path Y4 fixed; out of Y4's scope.
- **Authenticated-`/logout` success path** (`_logout` + `revoke_sessions_for_user`) — only the unauthenticated-401 case is tested; the success path is an untested minor coverage gap (the function mirrors `revoke_session`).

---

## Round 4 — verdict-bump re-review (RC-10): Y6 code-fixed (verified), remaining α = ADR reader-model inscription (Y7)

**Dispatch.** Junior pushed RW7 (`d2b5566`) to truly fix the Y6 production reader-connection race. RC-10 re-verification against the architect's four checkpoints + re-run the gates. **Route nothing** — the new finding (Y7) was architect-ruled α (inscribe-first) in-chat; recorded below.

**Verdict: `needs_architect` (one step from clean).** The Y6 race is **genuinely eliminated** and all four checkpoints pass; the only thing left is an honest-inscription α the architect ruled in-scope: ADR-039 + ADR-025 D6 still describe a *single* reader connection, which the per-thread pool now contradicts. Clean awaits round-5 (verify impl ↔ the updated ADRs).

### RW7 (`d2b5566`) verification — the four checkpoints, all pass

| Checkpoint | Verified |
|---|---|
| **(1) per-thread conns truly remove the shared-conn race** | `reader_executor` gets `initializer=_init_reader_worker`; each worker opens + owns its own `sqlite3` connection in `threading.local`. Every reader lambda now calls `ctx.get_reader_conn()` / `get_reader_store()` **at run-time on the worker thread** (`app.py:517/528/537/541/554/948/957/967/998`) — RW6's defect was binding `reader_conn = ctx.reader_store.conn` once on the async loop thread. WAL is set on the writer (`app.py:290`) and is a DB-file-level persistent mode → every per-thread reader conn inherits it → concurrent readers + writer, no `database is locked`. No route lambda uses the shared `reader_store` anymore (it is fallback-only). |
| **(2) writer single-conn serialisation untouched** | `writer_executor = ThreadPoolExecutor(max_workers=1)` (`app.py:316`), single `writer_conn`, `shutdown()` writer path unchanged. ADR-025 D6's writer-side (one serialised connection, atomic multi-append) is intact. |
| **(3) test now genuinely tests concurrent reads** | `conftest.py` upgraded to `max_workers=4` + the same per-thread initializer (matches prod) — the concurrency test exercises real concurrent reads, not the RW6 serialised-to-1 config. `test_concurrency.py` now **asserts** `not any(t.is_alive())` ("Subscriber threads timed out — reader hang?") — a hang now **fails the test** instead of being daemon-masked; `daemon=True` is honestly demoted to a CI safety-net comment. |
| **(4) RW6 overstated wording corrected (HR#5)** | conftest's wrong `max_workers=1 … fixes the concurrent-WS hang` comment is removed; RW7's commit explicitly states RW6 "masked this … left the production path broken." |

**Gates (re-run by me, round 4):** target test **15/15 PASS** under the genuinely-concurrent config (zero hangs) · **full pytest exit 0, 0 failed** (lone warning is the unrelated `test_net_trust` hung-DNS daemon thread) · **ruff exit 0** · **mypy "no issues, 275 files."** **Y1–Y4** untouched by RW7 → still resolved.

### 🟡 Y7 (round-4, NEW — ADR-as-contract integrity) — the per-thread reader pool is un-inscribed → **architect-ruled α (inscribe-first)**

The code is correct, but it now **contradicts the inscribed connection model** in two ADRs, neither updated:
- **ADR-039** (P4.5's own ADR, **Accepted this cycle**): line 19 (storage idiom) — *"a separate read-only **WAL reader** connection + read executor"*; line 137 (crash/concurrency posture) — *"validated on **the reader** connection"*. Both singular. → ADR-039 **mis-describes its own impl**.
- **ADR-025 D6**: line 80 — *"a separate read-only WAL connection"* (singular); line 99 Considered-Alternatives — ***"a thread pool of connections — Rejected for MVP … pooling is a perf forward hook (WAL)."*** → RW7 implements exactly the alternative D6 deferred.

Per the project discipline (*"ADR amendment IS required when changing an ADR decision"* + Architect Accept required), the per-thread reader pool must be **inscribed before ADR-039 is Accepted** — else the Accept records a false reader model. This is *within* the per-thread-reader decision the architect already ratified (an honest-inscription, not a new design choice).

**Architect routing (in-chat): α — inscribe-first.** Senior updates ADR-039 (line 19 / 137 → per-thread WAL reader pool: each `reader_executor` worker owns its connection) and annotates ADR-025 D6 (the line-99 deferred "thread pool of connections" forward-hook is now **activated** by P4.5 — rationale: the multi-user seam makes concurrent-read correctness in-scope; writer single-conn serialisation unchanged). Then R0-A round-5 verifies the impl matches the updated ADRs → clean.

### Below-bar residuals (still noting, not blocking)

- **`verify_password` disabled-user branch** (`users.py:201-202`) returns before scrypt — weaker oracle than the not-found path Y4 fixed; out of Y4's scope.
- **Authenticated-`/logout` success path** (`_logout` + `revoke_sessions_for_user`) — only the unauthenticated-401 case is tested; the success path is an untested minor coverage gap (mirrors `revoke_session`).

---

## Round 5 — verdict-bump re-review (RC-10): inscription landed, but RW7 was incomplete → NEW Y8 (middleware shared-conn race, empirically reproduced) → architect-routed α-RW8

**Dispatch.** Senior pushed the per-thread-reader inscription (`d3faf50`): ADR-039 (line 19/52/137) + an ADR-025 D6 annotation. Round-5 = final-gate verification: confirm the inscription matches the RW7 impl, the Y6 race is truly gone, suite stable green, Y1–Y4 resolved → clean. **Route nothing** — the new finding (Y8) was architect-ruled α (RW8) in-chat; recorded below.

**Verdict: `needs_architect` (NOT clean).** The inscription is well-written and the WS/route paths are correct, but tracing its *"validated on the per-thread WAL reader pool"* claim against the impl exposed that **RW7's per-thread fix was incomplete: the HTTP auth middleware was never migrated** and still races on the shared reader connection — **empirically reproduced** (valid users rejected under concurrency). The inscription therefore overstates. One more small fix (RW8) closes it.

### The inscription (`d3faf50`) — accurate for routes + WS

The ADR-025 D6 annotation + ADR-039 line 19 (storage idiom) / 52 (session validation) / 137 (crash-concurrency posture) now describe the per-thread WAL reader pool, the activation of D6's line-99 "thread pool of connections" forward-hook for the reader (multi-user concurrent-read correctness), and the unchanged writer single-conn. **Accurate for the route handlers + `_room_stream`** (which RW7 migrated to `get_reader_conn()`).

### 🟡 Y8 (round-5, NEW — RW7 incomplete; EMPIRICALLY REPRODUCED) — the HTTP auth middleware still uses the shared reader connection → **architect-routed α-RW8**

RW7 migrated the route handlers + WS to per-thread connections but **never touched `src/orchestrator/api/auth/middleware.py`** (its file-set was `app.py` + `conftest.py` + `test_concurrency.py`). The HTTP auth middleware — `_resolve_principal`, which runs on **every protected HTTP request** (the most-traveled auth path) — still has the exact Y6 race.

**Precise fix locations (for RW8) — mirror RW7's `_room_stream` change:**

| File:line | Current (racy) | Fix |
|---|---|---|
| `auth/middleware.py:85` | `reader_conn = ctx.reader_store.conn` — captures the **shared** conn on the loop thread | **delete this line** |
| `auth/middleware.py:92` | `lambda: validate_session(reader_conn, session_id)` | `lambda: validate_session(ctx.get_reader_conn(), session_id)` |
| `auth/middleware.py:103` | `lambda: validate_token(reader_conn, raw_token)` | `lambda: validate_token(ctx.get_reader_conn(), raw_token)` |

`ctx` is already in scope in `_resolve_principal` (read from `request.app.state.ctx`), so each lambda can resolve **its own worker thread's** connection at run-time via `ctx.get_reader_conn()` — identical to RW7's `_room_stream` fix. `grep` confirms `middleware.py:85` is the **only remaining** `ctx.reader_store.conn`-fed-to-`reader_executor` usage in `src/`; after RW8 it is the last shared-conn site migrated, and the `d3faf50` inscription becomes accurate.

**Empirical reproduction (mine, out-of-suite throwaway — deleted after running):** 40 concurrent authed HTTP requests through the middleware →
- **30 → 404** (auth OK, room not found — correct)
- **6 → 401** (a **valid** bearer token spuriously rejected — the race corrupts `validate_token`)
- **4 → `InterfaceError('bad parameter or other API misuse')`** (SQLite concurrent-single-connection corruption)

**Impact:** fail-closed (reject/500, never grant — **no auth bypass**), but P4.5's core multi-user auth path **rejects legitimate users + raises under concurrency** — exactly the multi-user condition P4.5 enables — and it makes the fresh `d3faf50` inscription (ADR-039 line 52/137: "validated on the per-thread WAL reader pool") **inaccurate for the HTTP path** (HR#5).

**Why uncaught:** round-4 grepped `app.py`, not `auth/middleware.py` (my miss); the suite is green because **no test exercises concurrent HTTP requests through the middleware** (the concurrency test is WS-replay-only). RW8 should add a concurrent-HTTP-auth regression test (the reproduction above is a ready template).

**Architect routing (in-chat): α — junior RW8** applies the three-line fix above + a concurrent-HTTP-auth regression test. Then R0-A round-6 re-runs the reproduction (expect all-404) + the full suite → clean.

### Below-bar residuals (still noting, not blocking)

- **`verify_password` disabled-user branch** (`users.py:201-202`) returns before scrypt — weaker oracle than the not-found path Y4 fixed; out of Y4's scope.
- **Authenticated-`/logout` success path** (`_logout` + `revoke_sessions_for_user`) — only the unauthenticated-401 case is tested; the success path is an untested minor coverage gap (mirrors `revoke_session`).
