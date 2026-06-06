---
task_id: P4.5
round: R0-B-on-plan-cross-family-external
reviewer_family: deepseek
reviewer_model_id: deepseek-v4-pro
reviews_acked:
  - architect-briefs/P4.5.md
  - senior-plans/P4.5.md
  - decisions/ADR-039-auth-identity-model.md
verdict: needs_architect
findings_count: { red: 0, yellow: 4, green: 7 }
---

# R0-B-on-plan — cross-family external review — P4.5 auth/multi-user/remote-bind

**Stance:** DeepSeek v4-pro, outside-Claude lens. Reviewed the DESIGN (plan + ADR-039 + brief) against the live working tree at `9d67c02`. No code has been built yet (plan-stage; `src/orchestrator/api/auth/` and `api/admin.py` do not exist). All findings are **design-level** — traced to concrete contradiction, ambiguity, or omission in the artifacts.

---

## Lens A — Identity / AuthN / AuthZ Trust Boundary

### 🟡 A-1 — WS handshake auth: design must nail reject-before-accept() sequencing

**Artifact:** Plan §P4.5-3(c), ADR-039 D4 (WS auth at handshake).

**Trace:** The current WS handler at `app.py:795` calls `await websocket.accept()` **immediately** with zero auth check. The plan correctly requires WS auth at handshake. However, the design states only "reject the upgrade if unauthenticated" without specifying the sequencing constraint: the rejection MUST happen **before** `websocket.accept()`, because once `accept()` is called the HTTP→WS upgrade is complete and the connection is open. A `websocket.close(code=4001)` after `accept()` still admits the connection briefly — a half-open-stream window.

The FastAPI/Starlette middleware runs **after** the WS upgrade handshake begins but **before** the handler body. If the middleware rejects with `401`, Starlette should close the connection without calling `accept()`. But if the middleware approach is per-route (the `Depends` alternative), the WS handler would need an explicit pre-accept check — which is easy to miss.

**Severity:** 🟡 (should). The design intent is correct; the implementation sequencing is load-bearing and should be explicit in the plan or ADR-039 D4 — specifically: "WS auth validation + rejection MUST complete before `websocket.accept()` is called."

**Confidence:** Medium. The middleware shape (P4.5-3, plan §5 #1) likely handles this correctly since Starlette middleware runs before the websocket endpoint body, but the plan does not explicitly state the accept-before-reject constraint.

---

### 🟡 A-2 — SameSite=Strict + CORS-with-credentials: deployment-origin interaction unresolved

**Artifact:** ADR-039 D3 (cookie: `SameSite=Strict`), ADR-039 D8 (CORS: configured origin + credentials), plan P4.5-6(b).

**Trace:** `SameSite=Strict` prevents the browser from sending the session cookie on **any** cross-site request — including same-origin requests initiated from a cross-site context. The interaction with CORS-with-credentials is load-bearing:

- **If the GUI is served from the same origin** as the API (React build served by FastAPI/uvicorn, or API reverse-proxied behind the same origin): `SameSite=Strict` works, CORS is unnecessary for the GUI, and the CORS middleware is purely a future-proofing / remote-client affordance. This is internally consistent.
- **If the GUI is on a different origin** (common dev setup: GUI on `:3000`, API on `:8000`): `SameSite=Strict` **blocks the cookie entirely** on cross-origin requests, and CORS-with-credentials cannot override it. The correct cookie setting for cross-origin is `SameSite=None` + `Secure` (with CSRF mitigations beyond the cookie).

ADR-039 D3 says "API being the sole same-origin boundary" — suggesting same-origin intent. But ADR-039 D8 says "CORS middleware restricting origins to a configured GUI origin" — suggesting the GUI *may* be on a different origin. The plan §5 #4 further defers the React GUI to a "frontend-track follow-on," so the actual deployment topology is undefined.

**Failure mode:** A developer deploys the GUI on a separate origin, sets the CORS origin accordingly, and finds the session cookie is never sent — silent auth failure (the user appears unauthenticated despite a valid session). The inverse (hardcoding `SameSite=None` when same-origin was intended) leaks the cookie on cross-site requests.

**Severity:** 🟡 (should). This is an architect decision, not a correctness bug. The ADR-039 should explicitly state the assumed deployment topology (same-origin vs cross-origin) and derive the cookie `SameSite` value from that assumption. If the topology is deferred, the residual should name this interaction explicitly.

**Confidence:** High. The SameSite/CORS interaction is a well-known footgun; the artifacts are ambiguous on the topology assumption.

---

### 🟢 A-3 — Forge guard design verified: server-derived principal, wire types identity-free

**Trace:** `IntentRequest` (`wire.py:48-61`) and `ConfirmRequest` (`wire.py:121-131`) both carry `extra="forbid"` and contain **no** `user_id`/`author`/`principal` field. The current author stamp at `app.py:486` is server-hardcoded. The plan (ADR-039 D7) extends this to `build_user_author(request_principal.user_id)` — still server-derived from the verified session, never the body. The ADR-039 considered-alternative "Let the client send `user_id`" is explicitly rejected. The forge guard is **constitutionally intact** in the design.

**Severity:** 🟢 (nit/confirmed). No finding — the design is spine-preserving on the forge-prevention axis.

---

### 🟢 A-4 — Fail-closed middleware design verified: middleware-with-explicit-public-allowlist

**Trace:** The plan §5 #1 surfaces the middleware-vs-Depends fork and chooses **middleware-with-explicit-public-allowlist** — fail-closed-by-default. A newly-added route is protected unless explicitly allow-listed. The alternative (per-route `Depends`) is correctly identified as fail-open-by-omission. The ADR-039 D4 encodes the middleware approach. The public allowlist (`/login` + `/health` + bootstrap) is minimal. No finding.

**Severity:** 🟢 (nit/confirmed).

---

### 🟢 A-5 — Session integrity design verified: fresh-issue, HttpOnly+Secure+SameSite, validate-rejects-expired/revoked

**Trace:** Plan P4.5-2: `session_id` via `secrets.token_urlsafe()` (cryptographically random, unguessable). Plan P4.5-3: login **creates a new session** (not adopting a client-supplied id — fixation-prevented), cookie is `HttpOnly`+`Secure`+`SameSite=Strict`. Plan P4.5-2 acceptance: expired session validates to `None`, revoked session validates to `None`. Logout revokes the session row + clears the cookie. The design is correct. No finding.

**Severity:** 🟢 (nit/confirmed).

---

### 🟢 A-6 — Credential storage design verified: scrypt + per-user salt + constant-time compare + token hashed

**Trace:** Plan P4.5-1: `hashlib.scrypt` (stdlib, memory-hard), per-user random salt, `hmac.compare_digest` for comparison, hash never logged/wired/evented. Plan P4.5-2: bearer token stored **hashed** (not plaintext). The `mcp/transport.py:97-108` secret-never-inlined discipline is cited as precedent. The plan §5 #2 surfaces the scrypt-vs-argon2 fork; the architect confirmed scrypt. No finding.

**Severity:** 🟢 (nit/confirmed).

---

### 🟢 A-7 — First-account bootstrap verified: out-of-band admin CLI, no unauthenticated user-create

**Trace:** Plan P4.5-1: admin CLI (`python -m orchestrator.api.admin create-user <id>`) writes directly to the `users` table — the operator's filesystem/DB access IS the pre-auth trust root. No unauthenticated signup/user-create endpoint exists in the plan. ADR-039 D2 inscribes the chicken-and-egg honestly. No finding.

**Severity:** 🟢 (nit/confirmed).

---

### 🟢 A-8 — Remote-bind fail-closed design verified: startup guard refuses non-localhost with zero users

**Trace:** Plan P4.5-6(a): startup **refuses** a non-localhost `--host` when no users are provisioned (or auth is disabled) — loud, at startup. Today's `__main__.py:20` has NO guard — `--host 0.0.0.0` comes up silently with auth off. The design closes this gap. No finding.

**Severity:** 🟢 (nit/confirmed).

---

## Lens B — Spine-Preservation / No-Regression

### 🟡 B-1 — Promotion-impact grep surface: 30+ test assertions bind `author="user"`

**Trace:** Grep of `tests/` for `author="user"` (hardcoded) found assertions in:
- `tests/api/test_intent.py` — lines 65, 185, 227, 279, 306, 426
- `tests/api/test_failure_modes.py` — lines 119, 211
- `tests/api/test_concurrency.py` — lines 51, 271, 284, 316, 329
- `tests/api/test_wire.py` — lines 50, 88
- `tests/api/test_read.py` — lines 104, 157, 187
- `tests/agents/test_dispatch.py` — line 77
- `tests/agents/test_integration.py` — lines 140, 170, 223, 277
- `tests/agents/test_should_agent_speak.py` — line 53
- `tests/agents/test_schema.py` — line 67
- `tests/agents/test_selection.py` — lines 341, 433, 561
- `tests/agents/test_tool_dispatch.py` — line 322

The plan P4.5-4 correctly identifies this as a forcing function ("promotion-impact grep") and P4.5-7 includes constitutional tests for the `is_valid_author` generalisation. However, the plan does **not** enumerate which of these 30+ assertions should change (become `user:<id>`) vs stay `"user"` (e.g., test fixtures that pre-date authentication, backward-compat assertions that bare `user` stays valid).

**Failure mode:** A test asserting `author="user"` after an authenticated intent silently passes because the test doesn't wire auth — the author stays `"user"` (hardcoded fallback), and the forge-prevention test (R0-B probe #1) never exercises the authenticated code path. The test blind spot: all existing intent tests bypass the auth boundary.

**Severity:** 🟡 (should). Not a design defect — the plan correctly names the risk. But the gap between "grep" and "reconcile" is implementation-load-bearing: the junior must update in-scope test fixtures to exercise the authenticated path AND preserve backward-compat assertions for bare `"user"`. The plan should explicitly state which test classes change and which stay.

**Confidence:** High. 30+ sites, and the plan doesn't categorize them.

---

### 🟡 B-2 — Confirm approver provenance: exact storage mechanism underspecified for idempotency interaction

**Artifact:** Plan P4.5-5, ADR-039 D6.

**Trace:** The plan says the approver `user_id` is recorded as "a `user_id` on the appended approval/confirm event's metadata, mirroring `DecisionMeta.user_id`'s shape." The confirm path appends two event types:
- `TOOL_CALL_CANCELLED` (cancel) — metadata: `ToolCallCancelledMeta{call_id}` (`event.py:362-370`)
- `TOOL_CALL` (approve) — metadata: `ToolCallMeta{tool_name, call_id, params}` (`event.py:203-212`)

Adding `user_id` to either schema is an additive field change. The plan does not specify:
1. Whether `user_id` goes on `ToolCallMeta`, `ToolCallCancelledMeta`, or both.
2. Whether the field is `str | None` (nullable, for backward-compat with pre-P4.5 events) or required.
3. Whether the `user_id` participates in the still-pending idempotency check (`PENDING_RESOLUTION_TYPES` scan at `app.py:659-668`).

The still-pending scan checks `later.type in PENDING_RESOLUTION_TYPES and str(later.metadata.get("call_id", "")) == pending_meta.call_id` — it does **not** inspect `user_id`. So adding `user_id` to the metadata does not break idempotency regardless of which schema it lands on. The idempotency is preserved. This is a specification gap, not a correctness bug.

**Severity:** 🟡 (should). The ADR-039 D6 should nail which metadata schema(s) gain `user_id` and whether it is nullable (backward-compat posture). This is pin-down-before-producer territory — the schema shape binds the audit trail.

**Confidence:** Medium. The idempotency is preserved either way; the gap is specificity, not correctness.

---

### 🟢 B-3 — Operation byte-frozen: no identity field, gate stays identity-blind

**Trace:** `Operation` at `scoring.py:19-34`: fields are `tool_id`, `initiating_agent`, `user_explicit_intent` (boolean), `params`, `estimated_cost_usd`. **No** `Principal`/`user_id`/identity field. The plan DP4a (ADR-039 HR#3) keeps it byte-frozen. The brief §4a lean is "keep the gate identity-blind." The plan P4.5-7 includes an empty-diff assertion on `scoring.py`. No finding — the gate is identity-blind and the design preserves it.

**Severity:** 🟢 (nit/confirmed).

---

### 🟢 B-4 — Author generalisation regex verified: bare `user` stays valid

**Trace:** Current regex at `event.py:405`: `^(user|system|agent:[a-zA-Z0-9_-]+)$`. Proposed: `^(user|user:[a-zA-Z0-9_-]+|system|agent:[a-zA-Z0-9_-]+)$`. The proposed regex:
- `user` → matches `user` alternative ✓
- `user:alice` → matches `user:[a-zA-Z0-9_-]+` ✓
- `user:` → no match (`+` requires ≥1 char) ✓
- `user:bad space` → no match (space not in `[a-zA-Z0-9_-]`) ✓
- `agent:claude` → matches `agent:[a-zA-Z0-9_-]+` ✓
- `system` → matches `system` alternative ✓

`build_user_author(user_id)` raises on empty id (mirroring `build_author` at `event.py:424-425`). The snapshot participant extraction (`snapshot.py:202`) filters on `_AGENT_PREFIX = "agent:"` — neither `user` nor `user:<id>` starts with `"agent:"`, so user-authored events correctly stay out of participants. No regression.

**Severity:** 🟢 (nit/confirmed).

---

### 🟢 B-5 — Confirm idempotency + crash-window preserved

**Trace:** The confirm handler at `app.py:611-731`:
1. **Still-pending check** (lines 659-668): position-anchored scan of events after the TOOL_CALL_PENDING for any `PENDING_RESOLUTION_TYPES` with the same `call_id`. **Unchanged** — the plan D6 adds only `user_id` provenance, not a new resolution type.
2. **TOOL_CALL author** (lines 677, 699): `build_author(pending_meta.initiating_agent)` — the **agent**, not the human. **Byte-unchanged** — the plan D6 explicitly preserves this.
3. **Double-confirm idempotency layer 2** (line 715): executor's call_id guard. **Unchanged.**
4. **Partial-turn envelope** (lines 146-161): `_ConfirmAppendError` vs `_ConfirmExecuteError` — append-fail = safe to retry, execute-fail = do NOT re-confirm. **Unchanged.**
5. **Crash window** (ADR-030 D7): append-then-execute — a crash after TOOL_CALL append leaves the call in the store for replay. **Unchanged.**

The plan adds approver `user_id` provenance WITHOUT touching any of these invariants. No regression.

**Severity:** 🟢 (nit/confirmed).

---

### 🟢 B-6 — Backend-authoritative preserved: API sole boundary, GUI carries credential but decides nothing

**Trace:** The plan (ADR-039 D7) explicitly states: "The GUI carries a credential (the session cookie) but still decides nothing — auth is enforced at the API (the sole boundary), not the client." ADR-026 HR#1/#2 (view+intent-only, API-sole-boundary) are annotated, not amended. The GUI login integration contract is pinned (ADR-039 D3) but no `ui/` code is built (plan §5 #4). The browser sends the session cookie automatically on same-origin requests; the API validates it server-side. No client-side authz decision exists. No regression.

**Severity:** 🟢 (nit/confirmed).

---

### 🟢 B-7 — Session concurrency on ADR-025 D6 two-connection model verified

**Trace:** Plan P4.5-2 acceptance: "session create/revoke run on the writer executor, validate on the reader (no cross-thread sqlite misuse — the `check_same_thread` discipline)." The writer executor is `ThreadPoolExecutor(max_workers=1)` (`app.py:259`) — single-writer-consistent. The reader executor has `max_workers=4` (`app.py:260`) for concurrent reads. `check_same_thread=False` on both connections (`app.py:249, 256`).

Session create/revoke on the writer: no TOCTOU between session-create and cookie-set (both happen within the same `_write_and_turn`-style serialized closure — well, for login, the session-create and cookie-set are in the same request handler on the writer). Session validate on the reader: a multi-second `run_turn` on the writer does NOT block auth checks — the reader connection serves `validate_session` independently via WAL reads. The ADR-025 D6 reader-liveness property is preserved. No finding.

**Severity:** 🟢 (nit/confirmed).

---

## Verdict

**`needs_architect`** — 0🔴 / 4🟡 / 7🟢.

No 🔴 findings: no concretely-traced identity forge, fail-open auth boundary, session fixation/replay/expiry-accept defect, gate-identity-blindness regression, pierced appender guard, confirm-idempotency break, or fail-open remote-bind exists in the DESIGN.

Four 🟡 findings — three requiring architect routing, one implementation-advisory:

| # | Lens | Finding | Architect action |
|---|---|---|---|
| A-1 | A | WS handshake auth: reject-before-accept() sequencing not explicit | α-absorb (clarify in ADR-039 D4) or δ-defer to impl (junior must nail it) |
| A-2 | A/B | SameSite=Strict + CORS-with-credentials: deployment-origin assumption unresolved | **Architect must clarify**: same-origin or cross-origin deployment topology? Derives cookie `SameSite` value. |
| B-1 | B | Promotion-impact grep surface: 30+ test assertions hardcode `author="user"` — plan names the risk but doesn't categorize which change vs stay | α-absorb (categorize in plan §P4.5-4 or P4.5-7) |
| B-2 | B | Confirm approver provenance: metadata schema target underspecified (ToolCallMeta? ToolCallCancelledMeta? Both?) | α-absorb (pin in ADR-039 D6) |

All seven 🟢 are **confirmation-only** — the design passes the spine-preservation probe on every constitutional axis (forge-prevention, fail-closed, gate-identity-blind, confirm-idempotent, backend-authoritative, is_valid_author-backward-compat, session-concurrency, no-new-LLMPurpose). The plan + ADR-039 are **architecturally sound** for the first identity boundary; the 🟡 findings are tightening/clarification, not redesign.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
