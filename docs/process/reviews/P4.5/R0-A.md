---
task_id: P4.5
round: R0-A
verdict: needs_architect
findings_count:
  red: 0
  yellow: 4
  green: 7
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
gates: ruff ✅ (exit 0) · mypy ✅ (no issues, 275 files) · pytest tests/api+tests/core ✅ (373 passed, exit 0)
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
