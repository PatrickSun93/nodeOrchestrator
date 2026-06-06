---
task_id: P4.5
round: R0-B-cross-family-external
reviewer_family: deepseek
reviewer_model_id: deepseek-v4-pro
reviews_acked:
  - architect-briefs/P4.5.md
  - senior-plans/P4.5.md
  - decisions/ADR-039-auth-identity-model.md
verdict: needs_architect
findings_count: { red: 0, yellow: 2, green: 2 }
---

# R0-B cross-family review — P4.5 impl (dual-lens: Lens A identity trust boundary + Lens B spine preservation)

**Reviewed:** `claude/P4.5-impl` (8 atomic commits, `git diff origin/main..HEAD`), 25 files, +2039/-61 lines.

**Method:** Full code trace of every new auth surface (`api/auth/`, `api/admin.py`, diffs to `app.py`/`__main__.py`/`event.py`) against both lens prompt checklists, plus verification of zero-diff on the constitutional spine (`autonomy/scoring.py`, `api/wire.py`). Cross-referenced with ADR-039 D1–D10 and the dual-lens plan-stage absorption round. No trust-the-types — every claim traced to `file:line`.

---

## Lens A — Identity / AuthN / AuthZ Trust Boundary

### A1. Principal is server-derived, never request-read (HR#1 / D7)

**Trace.** `IntentRequest` (`wire.py:48-61`) and `ConfirmRequest` (`wire.py:121-131`) are **zero-diff** from `origin/main` — no identity field added, `extra="forbid"` intact on both. `_LoginRequest` (`app.py:132-137`) also carries `extra="forbid"`. The forge guard at the schema layer is **type-impossible**: a client cannot place `user_id`/`author`/`approver_user_id` in any request body.

The author stamp (`app.py:548-553`):
```python
_principal = getattr(request.state, "principal", None)
_author = (
    build_user_author(_principal.user_id) if _principal is not None else "user"
)
```
`request.state.principal` is set by `AuthMiddleware.dispatch` (`middleware.py:69`) — only after `_resolve_principal` returns a non-None `Principal`. The principal is derived from session cookie (`validate_session`) or Bearer token (`validate_token`), both run server-side on the reader connection. **No wire body field reaches `_author`.**

The `approver_user_id` on confirm (`app.py:711-714`):
```python
_confirm_principal = getattr(request.state, "principal", None)
_approver_user_id = _confirm_principal.user_id if _confirm_principal else None
```
Same pattern — principal from middleware, never from `ConfirmRequest` body.

Constitution tests (`test_constitution.py:139-160`) confirm: `POST /intent` with extra `author` or `user_id` fields → 422; `ConfirmRequest.model_validate` with extra `approver_user_id` → `ValidationError`.

**Verdict: ✅ PASS.** Principal is server-derived from verified session/token, not request body. Forge-guard generalised correctly (ADR-025 D4 one level up).

### A2. Fail-closed on unauthenticated (HR#2 / D4)

**Trace.** `AuthMiddleware` (`middleware.py:46-70`) is registered via `_configure()` (`app.py:976-988`), called by **both** `create_app` (`app.py:1021`) and `_make_test_app` (`app.py:1028`). The Y1 wiring seam is correctly absorbed: `ctx` is stowed on `app.state` at lifespan (`app.py:1003`) or directly in `_make_test_app` (`app.py:1030`); the middleware reads `request.app.state.ctx` at request-time (`middleware.py:80`).

`PUBLIC_PATHS` (`middleware.py:35-39`): frozenset of `/login`, `/logout`, `/health`. Any path **not** in this set → `_resolve_principal()` → `None` → 401 JSON response before the route runs. Fail-closed-by-default confirmed: constitution test (`test_constitution.py:215-229`) registers a dummy `/test-new-route` on a minimal FastAPI app with only `_configure(app)` — the route returns 401 without explicit allow-listing. Parametrized test (`:195-213`) covers all 7 protected HTTP routes → all return 401.

WS auth (`app.py:902-939`): session cookie / Bearer token / query param checked **before** `await websocket.accept()` (`app.py:941`). Unauthenticated → `await websocket.close(code=1008)` then `return` (`app.py:937-938`) — `accept()` is never reached. Starlette's `websocket.close()` without prior `accept()` translates to an HTTP response rejecting the upgrade. The plan-stage A-1/M3 absorption (reject-before-accept) is correctly implemented. The comment at `middleware.py:11-13` correctly notes that `BaseHTTPMiddleware` does not see WS scopes, making the in-handler check **necessary, not redundant**.

**Verdict: ✅ PASS.** Middleware is fail-closed-by-default (explicit allowlist, new routes protected without opt-in). WS rejects before `accept()`. Both app factories share the same `_configure()` wiring.

### A3. Session integrity — fixation / hijack / replay / expiry

**Trace.** Session lifecycle (`session.py:76-91`):
- `create_session` generates `secrets.token_urlsafe(32)` — cryptographically random, 256 bits entropy. Client cannot predict or supply it.
- Login (`app.py:419-442`) calls `create_session` to generate a **fresh** session_id on every login — never adopts a client-supplied id. **No session fixation possible** (the attack requires the server to adopt a known id).
- `validate_session` (`session.py:106-123`) checks `revoked` flag AND `now_ms > expires_at` — both expired AND revoked sessions return `None`.
- `revoke_session` (`session.py:94-103`) sets `revoked=1` on the sessions row via writer executor.
- Logout (`app.py:444-456`) calls `revoke_session` + `resp.delete_cookie("session_id")` — server-side revocation, not just client-side cookie clear.
- Cookie: `httponly=True, secure=True, samesite="strict", max_age=86400` (`app.py:436-441`). Under the architect-ruled same-origin deployment (A-2), `SameSite=Strict` is correct and mitigates CSRF.

Session TTL: 24 hours (`_SESSION_TTL_MS = 86_400 * 1000`, `session.py:44`).

Constitution tests (`test_constitution.py:238-260`): expired session → `None`, revoked session → `None`, revoked token → `None`.

**Verdict: ✅ PASS.** No session fixation vector. Expired and revoked sessions rejected. Logout revokes server-side.

### A4. Token + credential storage

**Trace.** Password (`users.py:89-119`):
- `_hash_password` uses `hashlib.scrypt` (n=2^14, r=8, p=1, dklen=32) with `os.urandom(16)` per-user salt.
- `_verify_hash` recomputes scrypt then `hmac.compare_digest(dk.hex(), stored_hash_hex)` — constant-time.
- `verify_password` (`:178-199`) fetches hash+salt from DB, calls `_verify_hash`, `del stored_hash, stored_salt`, returns bool only. Hash never escapes.
- `get_user` (`:163-175`) selects only `user_id, created_at, disabled` — no credential columns.
- `create_user` (`:127-160`) hashes inside the function, `del pw_hash, pw_salt` after DB insert.
- The `User` dataclass (`:75-81`) has only `user_id, created_at, disabled`.

Bearer token (`session.py:131-179`):
- `create_token` generates `secrets.token_urlsafe(32)`, stores `SHA-256(raw_token).hexdigest()` in `user_tokens.token_hash`. Raw token returned once to caller; never persisted.
- `validate_token` hashes the presented token, looks up hash — raw token never in DB.
- Constitution tests confirm: password hash ≠ plaintext (`test_constitution.py:266-277`), `get_user()` returns no hash fields (`:279-285`), token stored as SHA-256 hex not plaintext (`:287-297`).

**Verdict: ✅ PASS.** scrypt + per-user salt + hmac.compare_digest for passwords. SHA-256 hashed token storage. No credential field leaks through `get_user`/`verify_password`.

**⚠️ 🟡 Finding Y1 (token-no-expiry):** The `user_tokens` table (`session.py:35-40`) has no `expires_at` column — tokens are **perpetual** until manually revoked. `validate_token` (`session.py:163-179`) checks only the `revoked` flag. Compare: sessions have a 24h TTL (`_SESSION_TTL_MS`). A leaked bearer token is a permanent credential. The ADR-039 D10 residual names "rotation" as not-built but does not name "tokens have no expiry" — a distinct concern (blast-radius limitation for a leaked secret). **The D10 residual should explicitly name "bearer tokens have no expiry" if it is intentional, or the `user_tokens` table should gain an `expires_at` column mirroring the session pattern.**

Confidence: medium (the risk is real — a leaked token is a permanent credential — but the tokens are high-entropy `secrets.token_urlsafe(32)` and the all-or-nothing authz model means every user is a full operator regardless; this is a posture concern, not an exploit vector).

### A5. Missing-authz on a constitutional actuator (RB-AUTHZ boundary)

**Trace.** Under DP3a (all-or-nothing authenticated-operator), any authenticated user may call any actuator. The D5 checkpoint seams are marked:
- **confirm-approve** — `app.py:695` comment: "D5 checkpoint seam #1: authenticated ⇒ allowed; role check would gate here."
- **plugin-admit** — no endpoint code exists (ADR-038 D5 pinned-not-built, P4.7). ADR-039 D9 pins the authz dimension.
- **config-write** — no config-write HTTP endpoint exists. User creation is via the out-of-band admin CLI only (`admin.py`).

All the actual routes (`/rooms/*`, `/intent`, `/confirm`) are protected by the auth middleware. **No actuator is reachable without authentication.** The `RB-AUTHZ` residual (ADR-039 D10) honestly states "any authenticated account is a full operator." The claim is true: there is no softened language, and every authenticated user can indeed actuate everything.

**Verdict: ✅ PASS.** No unauthenticated path to an actuator. Checkpoint seams marked. RB-AUTHZ residual honest.

**⚠️ 🟡 Finding Y2 (_is_public prefix-match):** `_is_public` (`middleware.py:43`) uses `path.startswith("/health")` in addition to the explicit `PUBLIC_PATHS` allowlist check. The `startswith` prefix match is redundant with `/health` already in the `PUBLIC_PATHS` frozenset, but additionally makes **any path starting with `/health`** (e.g., `/healthz`, `/health/status`, `/health-check`) public — even routes that are not in the explicit allowlist. This weakens the fail-closed-by-default design: a future route at `/health-check` would bypass the auth middleware without being added to `PUBLIC_PATHS`. The blast radius is small (health-check routes are benign), but this is a concrete deviation from "explicit allowlist" — the principle that every new route is protected unless explicitly listed. **Fix: remove the `startswith("/health")` check and rely solely on the `PUBLIC_PATHS` frozenset for explicit allowlisting.**

Confidence: high (the code is unambiguous; the prefix match is a departure from the explicit-allowlist design).

### A6. First-account bootstrap (chicken-and-egg)

**Trace.** Admin CLI (`admin.py:44-66`): `python -m orchestrator.api.admin create-user <id>` reads password from `ORCHESTRATOR_ADMIN_PASSWORD` env var or `getpass.getpass()` (stdin), opens its own SQLite connection, calls `init_auth_schema` then `create_user`, writes directly to the `users` table. The operator who can run the server already has filesystem + DB access — the CLI does not widen the trust root.

No `POST /users` or signup endpoint exists. Constitution test (`test_constitution.py:303-309`): unauthenticated `POST /users` → 401/404.

**Verdict: ✅ PASS.** Bootstrap is out-of-band only. No unauthenticated user-create surface.

### A7. Remote-bind fail-closed (D8)

**Trace.** `_check_remote_bind_guard` (`__main__.py:53-91`):
- `_is_loopback(host)` (`:38-50`) uses `ipaddress.ip_address(host).is_loopback` for `127.0.0.0/8` + `::1`, plus the literal `"localhost"` hostname. The M1 absorption (loopback-aware, not literal `127.0.0.1`) is correctly implemented.
- Loopback bind → guard returns immediately (permissive).
- Non-loopback + DB doesn't exist → loud error + `sys.exit(1)`.
- Non-loopback + DB exists but `count_users() == 0` → loud error + `sys.exit(1)`.
- Non-loopback + DB exists + ≥1 non-disabled user → passes.

`count_users` (`users.py:202-205`) counts only `disabled=0` rows — disabled-only users trigger the guard.

Remote-bind tests (`test_remote_bind.py`): loopback always permitted (`:52-57`), missing DB → SystemExit (`:60-64`), zero users → SystemExit (`:67-76`), with users → permitted (`:79-88`), only disabled users → SystemExit (`:92-104`).

CORS: not built (architect-ruled A-2 — same-origin deployment; CORS is a future cross-origin affordance, ADR-039 D8/D10). No `CORSMiddleware` registration anywhere in the diff.

TLS: no in-app TLS (`Secure` cookie requires it at reverse-proxy). TLS-at-deployment residual inscribed (ADR-039 D10).

Rate-limiting: not built. ADR-039 D8/D10 names it as a deferred residual.

**Verdict: ✅ PASS.** Remote bind refused at startup when no users provisioned. Loopback-aware. CORS/TLS/rate-limit dispositions match the architect-ratified plan.

---

## Lens B — Spine Preservation / No-Regression

### B1. Gate stays identity-blind (DP4a / HR#3)

**Trace.** `autonomy/scoring.py` — **zero diff** from `origin/main`. `Operation` model (`scoring.py:19-34`) field set is byte-frozen: `{tool_id, initiating_agent, user_explicit_intent, params, estimated_cost_usd}`. No `Principal`, `user_id`, or `author` field. `score()`, `decide_tier()`, `emit_gate_decision()` signatures unchanged.

Constitution tests (`test_constitution.py:317-345`): `Operation` has no `principal`/`user_id`/`author` field; `score()` signature has no such parameter; field set equals the expected 5-field frozenset.

No new `LLMPurpose` anywhere in `src/orchestrator/api/auth/` or the changed API files (grep-confirmed).

**Verdict: ✅ PASS.** Gate is identity-blind. No identity threading into scoring. No new LLMPurpose.

### B2. Author generalisation doesn't break appender guards / `is_valid_author` (D1)

**Trace.** `_AUTHOR_PATTERN` (`event.py:415-417`):
```
^(user|user:[a-zA-Z0-9_-]+|system|agent:[a-zA-Z0-9_-]+)$
```
- **bare `user`** — still valid (backward-compat for stored events + system-of-record default). The `author="user"` fallback at `app.py:550` (when no principal on request.state) would still validate.
- **`user:<id>`** — new authenticated form. `<id>` constrained to `[a-zA-Z0-9_-]+` (same charset as users table PK).
- **`agent:<id>`** — unchanged.
- **`system`** — unchanged.

Rejected forms: empty string, `user:` (empty id), `user:bad space`, `user:bad@`, `agent` (missing `:id`), `agent:` (empty id), `agent:bad name`, `User`, `USER`, `human`.

`build_user_author` (`event.py:449-458`): raises `ValueError` on empty `user_id`, returns `f"user:{user_id}"` otherwise. Single point of truth for the format.

Constitution tests (`test_constitution.py:361-404`): exhaustive parametrize over 7 valid + 10 invalid forms.

All `author="user"` Python consumers in the diff:
- `test_intent.py`, `test_failure_modes.py`, `test_concurrency.py` — updated to `f"user:{TEST_USER_ID}"` (CLASS A: authenticated `/intent` path, re-wired). ✅
- `test_confirm.py` — confirm tests use `_auth_headers(ctx)`, TOOL_CALL author still asserted as `agent:<id>` (not user-prefixed). ✅
- `test_core/test_event.py` — `is_valid_author` exhaustive test (CLASS B: unit test, bare `user` + `user:<id>` both checked). ✅
- `build_user_author` used in `app.py:550` and `test_constitution.py:398`. ✅

No grep hit for `author == "user"` in product code (only in tests). The fallback in `app.py:550` is the string literal `"user"`, which is correct (bare string literals are not `==` comparisons).

**Verdict: ✅ PASS.** Regex generalisation correct. Bare `user` backward-compat. No appender guard pierce. All test assertions categorized (CLASS A authenticated → user:<id>, CLASS B backward-compat bare user). B-1 absorption correctly executed.

### B3. Confirm stays idempotent + human-in-the-loop + crash-safe (ADR-030 D7 / HR#4)

**Trace.** `PENDING_RESOLUTION_TYPES` (`event.py:412-413`) — **zero diff** from `origin/main`. Still `{TOOL_CALL, TOOL_CALL_CANCELLED, TOOL_FAILED}`. The still-pending scan at `app.py:659-668` keys on `type ∈ PENDING_RESOLUTION_TYPES` + matching `call_id` and **never inspects `user_id`** — so the additive `approver_user_id` field cannot affect idempotency.

`approver_user_id` landing:
- `ToolCallMeta` (`event.py:218`): `approver_user_id: str | None = None` — **optional nullable field on existing meta**, not a new event type.
- `ToolCallCancelledMeta` (`event.py:380`): same pattern.
- Both are nullable for backward-compat with pre-P4.5 events (the still-pending scan ignores them).

Executed `TOOL_CALL` (`app.py:779-791`): author is `build_author(pending_meta.initiating_agent)` (agent-authored, **byte-unchanged from the ADR-030 D3 contract**). The `approver_user_id` is in `metadata`, recording who approved — provenance, not authorship.

Constitution tests:
- Double-approve → `already_resolved` (`test_constitution.py:410-455`). ✅
- Executed TOOL_CALL author is `agent:coordinator`, not `user:` (`:457-501`). ✅
- `approver_user_id == TEST_USER` in metadata (`:501`). ✅

**Verdict: ✅ PASS.** Idempotency preserved. TOOL_CALL agent-authored (unchanged). Approver provenance additive, not authorship.

### B4. Backend-authoritative / API-the-sole-boundary preserved (ADR-026 HR#1/#2)

**Trace.** `IntentRequest` / `ConfirmRequest` — zero diff, `extra="forbid"` intact. The GUI carries a credential (session cookie) but decides nothing — auth is enforced at the API middleware, not the client. No new client-trusted path. No decision (authz/principal resolution) moves client-side.

**Verdict: ✅ PASS.** Backend-authoritative intact. API still the sole boundary.

### B5. Concurrency / liveness surface (ADR-025 D6)

**Trace.** Session lifecycle:
- `create_session` (`session.py:76`) and `revoke_session` (`:94`) — documented "MUST run on the writer connection." Called via `ctx.writer_executor` in `app.py:427-429` (login) and `app.py:451-453` (logout). Single-writer serialised — no TOCTOU between session-create and cookie-set.
- `validate_session` (`session.py:106`) — documented "Runs on the reader connection." Called via `ctx.reader_executor` in `middleware.py:90-92` and WS handler `app.py:911-913`. A multi-second `run_turn` holding the writer does **not** block auth checks (reader WAL, `check_same_thread=False`).
- No `check_same_thread` violation — reader connects with `check_same_thread=False` and runs on its own executor; writer uses its own executor. All auth reads go through the reader connection.

Half-session crash window: session row written + committed in `create_session` before the cookie is set (`app.py:427-429` → `:434-441`). A crash between the two leaves an orphaned session row that expires on its own — harmless (client has no cookie, no auth bypass). Reverse case (cookie set before session row) is impossible because `resp.set_cookie` happens after `create_session` returns.

WS: auth reject before `accept()` → no unauthenticated subscriber drains the pub/sub bus. The WS stream is gated at handshake.

Constitution test (`test_constitution.py:550-559`): `validate_session` on reader connection → returns valid Principal.

**Verdict: ✅ PASS.** Sessions ride the two-connection model correctly. No liveness regression. WS pub/sub gated at handshake.

**🟢 Nit G1 (WS auth E2E test gap):** The constitution tests validate session/token directly on the reader connection and verify the HTTP 401 parametrize, but no test drives an unauthenticated `websocket_connect` and asserts the connection is rejected before upgrade. The WS auth code path (`app.py:902-939` → `close(1008)` → `return`) is straight-line and the rejection-before-accept pattern is code-verified, so this is a coverage nit, not a security concern.

### B6. Fail-closed direction on every new failure edge

**Trace.** Each new failure edge:
- `ctx` missing on `app.state` (`middleware.py:80`): `getattr` returns `None` → `_resolve_principal` returns `None` → 401. **Fail-closed.** ✅
- `validate_session` raises `OperationalError` (DB unreachable, table missing): exception propagates through middleware → Starlette returns 500. Not the clean 401, but handler never runs. **Fail-closed (500).** ✅ (500 is correct for infrastructure failure; an attacker cannot trigger a DB error on a healthy deployment).
- Unparseable cookie: `request.cookies.get("session_id")` returns `None` if no cookie exists, or a string if present. An invalid session_id → `validate_session` returns `None` (row not found). **Fail-closed (401).** ✅
- Remote-bind with no DB: `sys.exit(1)` at startup. **Fail-closed (refuse-startup).** ✅
- Remote-bind with zero users: `sys.exit(1)`. **Fail-closed.** ✅
- All-disabled users: `count_users` returns 0 → `sys.exit(1)`. **Fail-closed.** ✅

**Verdict: ✅ PASS.** All traced failure edges resolve fail-closed.

---

## Summary

| # | Lens | Severity | File | Finding |
|---|------|----------|------|---------|
| Y1 | A | 🟡 | `src/orchestrator/api/auth/session.py:35-40, :163-179` | **Bearer token has no expiry.** `user_tokens` table lacks `expires_at`; `validate_token` never rejects on age. Sessions have 24h TTL; tokens are perpetual until manually revoked. A leaked token is a permanent credential. Either add `expires_at` or explicitly name "tokens have no expiry" in the ADR-039 D10 residual. |
| Y2 | A | 🟡 | `src/orchestrator/api/auth/middleware.py:43` | **`_is_public` prefix-match weakens explicit allowlist.** `path.startswith("/health")` makes any future path starting with `/health` public without being in `PUBLIC_PATHS`. Deviates from the fail-closed-by-default design. Remove the prefix match; rely solely on the explicit `PUBLIC_PATHS` frozenset. |
| G1 | B | 🟢 | `tests/api/auth/test_constitution.py` | **WS auth rejection not E2E-tested.** No test drives `websocket_connect` without credentials and asserts rejection. The code path is straight-line and code-verified. Coverage nit only. |
| G2 | Both | 🟢 | `src/orchestrator/api/app.py:436-441` / ADR-039 D10 | **`Secure` cookie + localhost dev UX.** `Secure` flag is architect-ruled (TLS-at-deployment, same-origin). On plain-HTTP localhost, browser behavior varies. Design is honest; TLS-at-deployment residual inscribed. Awareness nit. |

**🔴 0 | 🟡 2 | 🟢 2**

---

## Design-level observations (no new findings, cross-checking the ratified leans)

- **Session fixation correctly prevented.** Login always calls `create_session()` which generates a fresh `secrets.token_urlsafe(32)` — the server never adopts a client-supplied session_id.
- **Logout revokes server-side** then clears cookie — not just client-side cookie deletion.
- **The admin CLI's `del password`** at `admin.py:66` is defense-in-depth — Python's GC would clear it anyway, but explicit is correct on a security path.
- **The `check_same_thread=False` discipline** is consistently applied: writer uses single-thread executor (`max_workers=1`), reader uses its own executor, and auth reads go through the reader connection. No cross-thread SQLite misuse.
- **The `_make_test_app` wiring** is correctly shared: `_configure(app)` + `app.state.ctx = ctx` before `_register_routes`. Tested-app == shipped-app at the auth crux — the Y1 absorption is correctly implemented.
- **The B-1 absorption** (30+ test assertion categorization) is correctly executed: `test_intent.py`, `test_failure_modes.py`, `test_concurrency.py` tests assert `user:<id>` through auth-wired clients; `test_confirm.py` confirms TOOL_CALL stays agent-authored.
- **The `ipaddress.is_loopback` guard** correctly covers `127.0.0.0/8` + `::1` + `localhost`. Tests cover all loopback variants and non-loopback IPs/hostnames. The M1 absorption is correctly implemented.

---

**Routing:** Route nothing (per the external-r0b-prompt — the architect routes). 2🟡 → verdict `needs_architect`. Both 🟡 are small, non-exploitable posture concerns (not identity-forge, not fail-open-auth, not session-defect, not gate-identity-leak, not appender-guard-pierce, not confirm-idempotency-break, not fail-open-bind). No 🔴. The architect may absorb (α) or defer (δ) either or both.
