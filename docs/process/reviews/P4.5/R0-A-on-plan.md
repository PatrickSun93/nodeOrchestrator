---
task_id: P4.5
round: R0-A-on-plan
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 10
reviewer: architect-partner
date: 2026-06-06
reviewed_artifacts:
  - docs/process/senior-plans/P4.5.md
  - docs/decisions/ADR-039-auth-identity-model.md
against: origin/main @ 9356bea (live substrate, verify-cited)
---

# R0-A-on-plan — P4.5: auth / multi-user / remote-bind (the first identity boundary)

**Dispatch:** architect-partner R0-A-on-plan of the senior plan + ADR-039 (Proposed), verify-cited against the live substrate. **Route nothing** — findings surfaced for architect routing at accept-time.

**NOT relitigated** (architect-ratified `9356bea`, design checked only for *honoring* them): DP1(b) real-multi-user seam, DP3(a) all-or-nothing operator, DP2 five-things scope, D2/MCP-OAuth deferral, TLS-at-proxy. The §5 senior-surfaced sub-decisions are checked **only for correctness** (per dispatch); none had a correctness defect — they are architect confirm-at-accept items, listed below, not findings.

**Verdict: `needs_architect`** — the plan + ADR-039 are strong, internally consistent with the ratified leans, and every verify-cited `file:line` claim checks out. **One 🟡 (Y1)** at the security crux (the fail-closed boundary's wiring seam) warrants architect routing before junior dispatch; **lean α** (senior-absorbable by naming the seam). Four minor impl-watch notes (M1–M4) are below the routing bar.

---

## Lens confirmations (the seven dispatch lenses — all honored; verify-cited)

**G1 — forge-guard generalised; principal server-derived, never request-read (lens 1).** HR#1 + D7 generalise ADR-025 D4 one level up. Verified: `api/app.py:486` `author="user"  # HARDCODED — never read from request`; `IntentRequest` (`wire.py:48-61`) and `ConfirmRequest` (`wire.py:121-131`) both `extra="forbid"` with **no** author/id/principal field — so an identity field on the wire is type-impossible, exactly as today. P4.5-4 stamps `author=build_user_author(principal.user_id)` from the session (P4.5-3), P4.5-5 records the approver from the principal — both "never from the body," with forge tests asserting no body field reaches `author`/`user_id`. Design honors the lens.

**G2 — fail-closed-on-unauthenticated (lens 2).** HR#2 + D4: middleware-with-explicit-public-allowlist, `401` **before** any handler/append/`run_turn`, parametrized over all 7 HTTP routes + WS-at-handshake, plus a fail-closed-**by-default** test (a new dummy route is protected without being allow-listed). Verified the surface it must cover: 7 HTTP routes (`app.py:387/394/405/413/430/441/611`) + 1 WS (`app.py:781`), and **zero** middleware/CORS/`Depends` exist today (grep-clean across `api/`). The *design* is sound; the *wiring* is Y1.

**G3 — author-format generalisation is backward-compatible (lens 1/4c).** Verified `core/event.py:405` `_AUTHOR_PATTERN = ^(user|system|agent:[a-zA-Z0-9_-]+)$` and `build_author` (`:416`, single-point-of-truth, raises on empty). The plan's `^(user|user:[a-zA-Z0-9_-]+|system|agent:[a-zA-Z0-9_-]+)$` keeps **bare `user`** valid (stored-event + system-of-record default) and mirrors `build_user_author` on `build_author` — the promotion-impact grep (P4.5-4) and the exhaustive `is_valid_author` guard (P4.5-7 #9) are the right forcing functions.

**G4 — gate stays identity-blind; no new `LLMPurpose` (lens 3).** Verified `autonomy/scoring.py:19-34` `Operation{tool_id, initiating_agent, user_explicit_intent, params, estimated_cost_usd}` — **no actor/principal**; the tier is reversibility-only. P4.5-7 #7 (empty-diff on `scoring.py`) + #8 (no new `LLMPurpose`) are grep-checkable: `LLMPurpose` (`llm/purposes.py:25`) has 10 members, **all content-gen** — an auth purpose would be a visible regression. Honored.

**G5 — confirm: TOOL_CALL stays agent-authored; ADR-030 not regressed (lens 4).** Verified both confirm paths stamp `author=build_author(pending_meta.initiating_agent)` — approve (`app.py:699`) and cancel (`app.py:677`) — reconstructed from the persisted record, on `ctx.writer_executor` (atomic), with position-anchored still-pending (`:659-667`) + executor call_id guard (`:713`) idempotency. D6 adds approver **provenance** only; P4.5-5 asserts the executed `TOOL_CALL` author is empty-diff and idempotency/partial-turn unchanged. Honored (see M4 for the metadata-landing watch).

**G6 — fail-closed boundary design + the never-built CORS gap (lens 2).** `create_app` (`app.py:839-859`) is a lifespan factory; `_register_routes(app, ctx)` (`:379`) is the closure-capture seam. Confirmed: no CORS today despite ADR-025 D7's promise — D8's "build the never-built CORS" is verify-grounded.

**G7 — `RB-AUTHZ` inscribed honestly + checkpoints pinned additive (lens 5).** D5 + D10 name the three constitutional-actuator seams (confirm-approve / plugin-admit / config-write) as no-op "authenticated ⇒ allowed" comments so DP3b is additive; `RB-AUTHZ` reads in the `RB-FS/NET` voice ("any authenticated **or compromised** account has full actuation … irreversible HARD tools + plugin admission"), with the explicit "flips dangerous if members become non-fully-trusted" condition. P4.5-5 marks seam #1 as a named no-op. Honored.

**G8 — ADR-038 D5 mgmt-endpoint authz dimension pinned, no code (lens 6).** D9 + P4.5-8 annotation pin "operator action requiring an authenticated principal," explicitly **no endpoint code** (P4.7 frontend track owns the build) — inscribe-before-producer, the right move. Honored.

**G9 — first-account bootstrap + credential posture (lens 7).** D2: out-of-band admin CLI (`python -m orchestrator.api.admin create-user`) as the pre-auth trust root (= the `config/plugins.yaml`-author root, not widened); `hashlib.scrypt` (stdlib, memory-hard, no new dep) + per-user salt + `hmac.compare_digest`; hash/salt **never logged/wired/evented** (the `mcp/transport.py:107` `api_key_env`-never-inlined discipline, verified). Residual posture (reset/rotation/MFA/lockout/signup not built) inscribed in D10. Honored.

**G10 — remote-bind gap + cite accuracy.** Verified `api/__main__.py:20` `--host` default `127.0.0.1`, the "must add authentication/TLS before exposing externally" comment, and **no bind guard** today (`uvicorn.run(app, host=args.host, …)`) — D8's fail-closed remote-bind closes the real gap. Two further verify-cited claims confirmed accurate: the FE author-label ripple (`authorLabel` exists in `ui/src/uiStrings.ts`; `authorLabel("user") → "你"`, so `user:<id>` falls back to generic until the FE follow-on — exactly the named, not-built ripple) and `record_preference` (`memory/entity.py:107`) mandating a non-empty `user_id` (the audit string D1 authenticates).

---

## 🟡 Y1 — The fail-closed middleware's wiring seam is under-specified at the security crux (P4.5-3 "Where" + ADR-039 D4)

**The finding.** P4.5-3's "Where" registers the auth middleware at **`create_app` (`app.py:839-859`)** and the routes at `_register_routes (:379)`. Two live-substrate facts make that single named site insufficient — and the gap sits on the one deliverable the whole slice exists to build:

1. **ctx-availability / Starlette timing.** The auth middleware must reach the session store to validate a cookie/token — i.e. it needs `ctx`. But `create_app` builds `ctx` and calls `_register_routes` **inside `lifespan`** (`app.py:849-850`), i.e. *after* startup begins. Starlette builds its middleware stack on the first `__call__` (the lifespan call included) and then `add_middleware` raises `RuntimeError: Cannot add middleware after an application has started`. So the middleware **cannot** reuse the existing closure-capture site (`_register_routes`, inside lifespan); it must be registered at **construction** (before the instance serves) — which is **before `ctx` exists**. The idiomatic resolution is `app.state` (lifespan startup stows `ctx`; the middleware reads `request.app.state` at request-time) — but **there is no `app.state` usage today** (the codebase is pure closure-capture). The plan names none of this.

2. **Test-factory coverage / tested-app ≠ shipped-app.** **37/37** API-test references build the app via **`_make_test_app(ctx)` (`app.py:862`); 0 use `create_app`.** P4.5-3's acceptance (401 over all 7 routes parametrized; fail-closed-by-default dummy route; WS-reject) and P4.5-7's fail-closed guards all run through `_make_test_app`. If the middleware is registered **only** in `create_app` (the named site), the shipped boundary is exercised by **no test**, and the test app diverges from production at the security crux — precisely the class of gap Lens A/B hunt.

**Why it rises above impl-watch.** It is an *internal inconsistency in the plan*: the acceptance tests (P4.5-3/-7) require the middleware in the `_make_test_app` path, but the "Where" names only `create_app`, which no test exercises — and the existing closure-capture pattern the "Where" implies is structurally unavailable to middleware. A junior following "Where" literally lands middleware in `create_app`, then finds the acceptance suite (via `_make_test_app`) can't see it.

**Recommendation (surface, not a routing decision).** Have the plan name a **shared construction-time configure step both factories call** (so the boundary is tested via the same wiring it ships) and the **ctx-resolution mechanism** (e.g. `app.state` populated at lifespan startup), so the fail-closed gate is wired once and exercised by the suite. I do **not** prescribe the shape — that is senior's to draft.

**Lean: α (senior-absorbable before junior dispatch)** — a "Where" amendment to P4.5-3 + an acceptance line that the boundary test runs through the production wiring. Architect routes.

---

## Minor / impl-watch (M1–M4 — below the routing bar; junior-resolvable, listed for the record)

- **M1 — bind-guard "localhost" definition (P4.5-6 / D8).** "Refuses bind beyond `127.0.0.1`" should treat *localhost* as `127.0.0.0/8` + `::1` + `localhost`, not the literal string `127.0.0.1` — else a legitimate `::1` bind is falsely refused and a specific-LAN-IP bind may slip the guard. Impl detail; name the intent.
- **M2 — `/login` rate-limit can't be "per-identity" (ADR-039 D8 wording).** D8 lists "thin per-identity limiter on … `/login`," but at `/login` there is **no authenticated principal yet** (that is the brute-force surface) — `/login` throttling is per-claimed-`user_id` / per-IP; only `/intent`·`/confirm` can be per-identity. Wording, and only if rate-limiting is built (it is thin-or-deferred per §5).
- **M3 — WS auth must reject *before* `accept()` (P4.5-3c).** `app.py:795` does `await websocket.accept()` first; the handshake auth must validate and reject **before** `accept()` (not accept-then-close). The plan's "reject the upgrade if unauthenticated" is right; flag the ordering. (Note also: a `BaseHTTPMiddleware` does not see WS scope, so the separate in-handler WS check the plan already has is *necessary*, not redundant — correct as planned.)
- **M4 — confirm-provenance landing should be an optional field on existing meta, not a new event type (P4.5-5).** "Mirroring `DecisionMeta.user_id`'s shape" should land as an optional `user_id`/`approved_by` on the existing `ToolCallMeta` / `ToolCallCancelledMeta` (the two events confirm appends), **not** a new approval event type — a new type would ripple into `PENDING_RESOLUTION_TYPES` (idempotency layer 1) and snapshot derivation, which HR#4 requires unchanged. The plan's lean already points here; make it explicit.

---

## §5 senior-surfaced sub-decisions — architect confirm-at-accept (NOT findings)

Per dispatch, checked for correctness only; **none has a correctness defect** — all five are the conservative, spine-preserving draft, awaiting architect confirm-or-redirect at accept (senior absorbs α if redirected):

1. **Middleware-fail-closed vs per-route `Depends`** — middleware is fail-closed-by-default (the safer choice; matches HR#2). Correct. (Its *wiring* is Y1, independent of this fork.)
2. **`hashlib.scrypt` vs argon2 dep** — stdlib, memory-hard, swappable behind the verify interface; matches "simplest credential now." Correct.
3. **Rate-limit thin-on-`/login` vs defer** — either is spine-safe (residual named in D10 if deferred). Correct (see M2 on wording).
4. **GUI login contract-only vs minimal React** — contract-only matches the P4.7 frontend-track precedent. Correct.
5. **Per-user token in-scope vs defer** — in-scope is needed for the `TestClient` end-to-end path given #4. Correct.

---

## Cite-accuracy note

Every verify-cited `file:line` in the plan §1/§13 and ADR-039 Context that I checked resolves correctly against `origin/main`: `app.py:486`, the 7-routes+1-WS map, `wire.py:48-61/121-131`, `event.py:405`/`build_author`/`DecisionMeta:139-177`, `scoring.py:19-34`, `mcp/transport.py:97-108`, `__main__.py` bind, `memory/entity.py:107`, the no-CORS/no-middleware grep, the `LLMPurpose` content-gen set, and the `ui/src/uiStrings.ts authorLabel` FE ripple. The plan's self-discoveries (CORS-never-built, no DI seam for a principal) are grep-confirmed. Claims-with-cites discipline (W-004 (a)) held.

## Authorship note
Architect-partner R0-A-on-plan, verify-cited vs `origin/main` @ `9356bea`. The plan + ADR-039 honor all seven dispatch lenses and the ratified DP1b/DP3a/DP2-scope/D2-defer/TLS-at-proxy; one 🟡 (Y1, lean α) at the fail-closed boundary's wiring seam, four impl-watch minors, five §5 sub-decisions for architect confirm-at-accept. **Route nothing** — architect decides Y1 + the §5 confirms at the ADR-039 Accept moment.
