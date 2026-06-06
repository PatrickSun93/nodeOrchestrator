# External R0-B prompt — P4.5 (auth / multi-user / remote-bind — the first identity boundary) — MANDATORY dual-lens

> **Dispatch context.** `requires_cross_family_review: true` (ratified; P4-roadmap §8 — D1+D2 heavy, D3 single-lens). You are the **cross-family** reviewer (DeepSeek via the role-rewriting proxy). This is the **plan-stage** prompt; the architect dispatches it at **impl stage** against the impl branch. P4.5 is the **identity** half of the Wave-2 trust work — orthogonal to every prior slice, which protected against a *client forging the backend's decisions* (forge-prevention, backend-authoritative). P4.5 adds the boundary the spine never had: **proving which human is on the other end**, and **what that human may do**. Everything before P4.5 assumed one trusted operator on localhost (ADR-025 D7: "Auth: none"). It introduces a per-request authenticated principal (DP1b), cookie-session + per-user token auth (DP2), an all-or-nothing authenticated-operator authz model (DP3a), and remote-bind. **Your job is to find where a request can act as someone it isn't (Lens A), or where adding identity silently broke the existing constitutional spine (Lens B).** These two lenses are genuinely orthogonal — "auth is insecure" vs "auth broke ADR-025/026/030."

---

## Your stance

Take a deliberately **outside-Claude** lens. Over-correct for Claude's biases: trust-the-types-means-trust-the-runtime, "the model has a `user_id` field therefore identity is proven," over-engineering, agreeableness, "the middleware is registered therefore the boundary is fail-closed." **Trace failure modes across the request → auth-boundary → principal → handler → event chain** and ask: "what happens when the cookie is forged / replayed / fixed before login / the session is expired-but-accepted / a route is added without protection / the principal is read from the body / a `user:<id>` author is smuggled / a remote bind comes up with auth off / two tabs race a login or a confirm?" Default to **refuted/skeptical** when uncertain; a finding you can't substantiate by tracing the code is not a finding. Cite `file:line` or `artifact §`.

## Artifact bundle — read from disk (in-repo dispatch)

Read in full:
1. `docs/process/architect-briefs/P4.5.md` — the decision-surface (5 DPs + leans + the §6 watch-list + the §5 two-lens design).
2. `docs/process/senior-plans/P4.5.md` — the plan (atomics P4.5-0..8 + the 5 surfaced sub-decisions in §5).
3. `docs/decisions/ADR-039-auth-identity-model.md` — the proposed ADR (D1–D10 + the `RB-AUTHZ` / TLS-at-deployment / credential-posture residuals).

Plus the live substrate it threads (probe claims against the working tree):
- `src/orchestrator/api/auth/` (the new module — `users.py`, `session.py`, `token.py`, `principal.py`, `middleware.py`) + `api/admin.py` (the first-account bootstrap CLI).
- `src/orchestrator/api/app.py` (the auth boundary in `create_app` `:839`; the route registration `:379-836`; the **author stamp** `:486`; the **confirm** handler `:611-731`; `AppContext` `:95-120`; `_build_context` `:240-376`; **no CORS/middleware existed pre-P4.5** — verify what was added).
- `src/orchestrator/api/wire.py` (`IntentRequest:48-61`, `ConfirmRequest:121-131` — confirm **no** identity field was added — the forge surface stays type-impossible).
- `src/orchestrator/core/event.py` (`is_valid_author:405` — the generalised regex; `build_author:416` + the new `build_user_author`; `DecisionMeta:139-177`).
- `src/orchestrator/autonomy/scoring.py` (`Operation:19-34` — must be **byte-frozen**; identity-blind gate).
- `src/orchestrator/api/__main__.py` (`--host` bind + the new fail-closed-remote-bind guard).
- ADR-025 (D4 forge-prevention / D6 two-connection single-writer / D7 localhost-trust), ADR-026 (HR#1/#2), ADR-030 (D3 step 5 / N1 / D7 idempotency), ADR-038 (D5).

---

## Lens A — the IDENTITY / AUTHN / AUTHZ TRUST BOUNDARY (the "auth done wrong" adversary)

Can a request **act as someone it isn't**, or reach an actuator it shouldn't? Trace each:

1. **Principal is server-derived, never request-read (the forge crux — ADR-039 HR#1 / D7).** The authenticated identity must come **only** from a server-verified session cookie or server-issued token — **on the server**. Trace: can any wire body field (`IntentRequest`/`ConfirmRequest`/`/login` body) influence the stamped `author` / the recorded `user_id` / the resolved principal? Does `IntentRequest`/`ConfirmRequest` accept an identity field (`extra="forbid"` must keep it type-impossible)? Is the `author="user:<id>"` stamp at `app.py:486` derived from the principal, **never** the body?
2. **Fail-closed on unauthenticated (ADR-039 HR#2 / D4).** Every non-public route + the WS must reject an unauthenticated request with `401` **before** any handler logic / append / `run_turn`. Trace the middleware: is it **fail-closed-by-default** (a newly-added route protected unless explicitly allow-listed) or **fail-open-by-omission** (a route unprotected unless it opts in)? Is the public allowlist minimal + correct (`/login` + bootstrap + health only)? Is the WS upgrade rejected at handshake when unauthenticated — or does the stream open and only fail later?
3. **Session integrity — fixation / hijack / replay / expiry.** Trace the session lifecycle: is the `session_id` cryptographically random (`secrets`), opaque, unguessable? Is a **pre-login session fixation** possible (does login **issue a fresh** session id, not adopt a client-supplied one)? Is an **expired** or **revoked** session accepted (the validate path must reject both)? Does logout actually revoke (not just clear the cookie client-side)? Is the cookie `HttpOnly` + `Secure` + `SameSite=Strict` (XSS-theft + CSRF + cleartext-leak posture)?
4. **Token + credential storage.** Is the password hashed with a memory-hard KDF (`hashlib.scrypt`) + per-user random salt + constant-time compare (`hmac.compare_digest`)? Is the per-user bearer **token** stored **hashed** (not plaintext — a DB read must not yield usable tokens)? Does the password hash / salt / session id / token **ever** appear in a log / a wire response / an event (the `mcp/transport.py:107` secret-never-inlined discipline)?
5. **Missing-authz on a constitutional actuator (the `RB-AUTHZ` boundary — DP3a / D5).** Under all-or-nothing (DP3a), any authenticated user is a full operator — that is **ratified**, not a finding. But probe: is the actuator actually behind the **auth** boundary at all? A HARD-confirm approve (`/confirm`), a plugin-admit (ADR-038 D5 endpoints — pinned, not built), a config-write / user-create — each must require an **authenticated** principal (even if not a *role*). Is there any actuator reachable **without** authentication? Are the three checkpoint seams (confirm-approve / plugin-admit / config-write) actually marked where a role check would gate (so DP3b is additive), and is the `RB-AUTHZ` residual **honest** (it says "any authenticated account is a full operator incl. irreversible HARD tools + plugin admission" — is that true + un-softened)?
6. **First-account bootstrap (the chicken-and-egg).** Auth gates everything incl. user creation. Trace the bootstrap: is the first account created **out-of-band only** (the admin CLI writing directly to the `users` table — the operator's pre-auth filesystem trust root)? Is there **no** unauthenticated user-create / signup endpoint that would let anyone provision themselves (a fail-open onboarding hole)? Does the CLI widen the trust root beyond what the operator already has?
7. **Remote-bind fail-closed (D8).** Binding beyond `127.0.0.1` with **no users provisioned** (or auth off) must be **refused at startup** (loud). Trace `__main__.py` / startup: can a `--host 0.0.0.0` come up with the auth boundary disarmed (the today-state the slice must close)? Is CORS restricted to the configured origin (not `*` with credentials — the credentialed-wildcard CORS footgun)?

## Lens B — SPINE-PRESERVATION / NO-REGRESSION (the "did identity break the existing constitution" adversary)

Does adding auth **regress** an invariant the prior ADRs established? Trace each:

1. **Gate stays identity-blind (DP4a / ADR-039 HR#3).** `autonomy/scoring.py` `Operation` (`:19-34`) must be **byte-frozen** — no `Principal`/`user_id` reaches `score`/`decide_tier`/`emit_gate_decision`; the tier is reversibility-only, never actor-dependent. Trace: does any auth code thread identity into the gate? Is there a new per-user threshold / per-user LLM judgment (forbidden — CLAUDE.md routing=code)? Confirm **no new `LLMPurpose`** on the auth surface (grep).
2. **The `author` generalisation doesn't break the appender guards / `is_valid_author` (D1 — the t4-adjacent change).** The regex generalises to `^(user|user:[a-zA-Z0-9_-]+|system|agent:[a-zA-Z0-9_-]+)$`. Trace: does **bare `user`** stay valid (the events already in the store + the system-of-record default must not become invalid)? Does `user:<id>` validate, and do the invalid forms (`user:`, `user:bad space`, empty) reject? Does the generalisation pierce any t4 appender guard (the ADR-030 D1 "two appenders, each downstream-of-gate" property — a `user:<id>` author must not let a client forge an agent/system event)? Does the snapshot derivation / any `author=="user"` consumer break?
3. **Confirm stays idempotent + human-in-the-loop + crash-safe (ADR-030 D7 / HR#4).** D6 adds the approver `user_id` provenance. Trace: is the executed `TOOL_CALL` **still `author=agent:<initiating_agent>`** (`app.py:699` — byte-unchanged; the human supplied approval, not authorship)? Is the `user_id` recorded from the **principal, not the body** (forge)? Does the provenance addition regress the **position-anchored still-pending check** (ADR-030 D3 step 3), the **double-confirm idempotency** (two tabs racing), the **partial-turn `stage` envelope** (D5), or the **append-then-execute crash window** (D7)?
4. **Backend-authoritative / API-the-sole-boundary preserved (ADR-026 HR#1/#2).** The GUI now carries a credential (the session cookie) but must **still decide nothing** — auth is enforced at the **API**, not the client. Trace: does any decision (authz / principal resolution) move client-side? Is the API still the sole boundary (no new client-trusted path)?
5. **The new concurrency / liveness surface (ADR-025 D6).** Sessions ride the single-writer. Trace: are session create/revoke on the **writer** executor (single-writer-consistent, no TOCTOU between session-create and cookie-set) and session **validate** on the **reader** connection (so a multi-second `run_turn` holding the writer thread does **not** block auth checks — the ADR-025 D6 reader-liveness property)? Does a `check_same_thread` violation lurk (a session validated on the wrong connection)? Does remote-bind exposing the pub/sub stream to non-localhost get gated by the WS-handshake auth (an unauthenticated subscriber rejected at connect, not draining the bus)? Is there a half-session crash window (a session row written but the cookie never set, or vice-versa)?
6. **Fail-closed direction on every new edge.** A malformed/absent `users` table, a session-store read error, a bind with the DB unreachable, an unparseable cookie — each must resolve **fail-closed** (refuse / `401` / refuse-startup), never fail-open (admit unauthenticated). Trace each new failure edge for its direction.

---

## NOT IN SCOPE to re-raise (architect-decided / constitutional — probe whether the DESIGN honors them, do not relitigate)

- **DP1(b) real-multi-user seam (per-request principal; `author`→`user:<id>`); simplest-credential-now; OAuth/OIDC (c) DEFERRED** — architect-ratified. Probe the principal is server-derived + the seam is additive, **not** whether to build OAuth now.
- **DP3(a) all-or-nothing authenticated-operator; NO role model; `RB-AUTHZ` inscribed** — architect-ratified. Probe the checkpoint seams are pinned + the residual is honest, **not** whether to build RBAC. (A *non-fully-trusted-members* deployment would flip this — but that is the architect's deployment-intent call, not yours.)
- **DP2 cookie-session + optional per-user token; TLS at deployment/proxy (not in-app); rate-limiting thin-or-residual; D2/MCP-OAuth DEFERRED** — architect-ratified. Probe the mechanism's correctness + the TLS/rate-limit dispositions are honestly residual'd, **not** whether to terminate TLS in-app or build OAuth.
- **DP4 gate identity-blind; confirm gains approver provenance (tool stays agent-authored); forge-guard generalises (server-derived); ADR-038 D5 authz dimension pinned (no endpoint code)** — architect-ratified. Probe the threading honors the spine.
- **Management endpoints contract-only authz-dimension (no impl this slice); React GUI login contract-only (no `ui/` code)** — architect-ratified (D9 / §5 #4). Probe the contract is coherent + backend-authoritative, **not** whether to build the endpoints/UI.
- **New ADR-039; no new `LLMPurpose`; gate-unchanged; `Operation` byte-frozen; the executed `TOOL_CALL` agent-authored** — constitutional. Probe whether the DESIGN honors them.
- The five plan §5 sub-decisions (middleware-fail-closed / scrypt / thin-`/login` / contract-only-GUI / token-in-scope) are **architect-confirm** items — if you see a *correctness* problem with the drafted choice, raise it as a finding; do not relitigate the choice itself.

## Output

Land at `docs/process/reviews/P4.5/R0-B.md` with YAML frontmatter:

```
---
task_id: P4.5
round: R0-B-cross-family-external
reviewer_family: <deepseek | gpt-5 | gemini | other>
reviewer_model_id: <specific model>
reviews_acked:
  - architect-briefs/P4.5.md
  - senior-plans/P4.5.md
  - decisions/ADR-039-auth-identity-model.md
verdict: <clean | needs_architect | blocking>
findings_count: { red: N, yellow: N, green: N }
---
```

Per finding: `file:line` (or `artifact §`), the failure mode **traced** (the concrete identity-forge / fail-open-auth / session defect / missing-authz / un-honest-residual for Lens A; the concrete spine-regression / gate-identity-leak / appender-guard-pierce / confirm-idempotency-break / liveness-regression for Lens B), severity (🔴 must-fix / 🟡 should / 🟢 nit), and your confidence. **Route nothing yourself** — the architect routes (α absorb / β defer / γ reject / δ later). A **🔴 only** for a concretely-traced identity forge (a request acting as someone it isn't), a fail-open auth boundary (an unauthenticated path to an actuator), a session fixation/replay/expiry-accept defect, a gate-identity-blindness regression, a pierced appender guard, a confirm-idempotency break, or a fail-open remote-bind — not a hypothetical.

**Verdict semantics:**
- `clean` = 0🔴 / 0🟡 / any 🟢 → architect proceeds to Accept ADR-039 + junior dispatch.
- `needs_architect` = ≥1🟡 OR an issue needing routing → architect Decision blocks.
- `blocking` = ≥1🔴 (identity-forge / fail-open-auth / session-defect / gate-identity-leak / pierced-appender-guard / confirm-idempotency-break / fail-open-bind) → plan + ADR-039 revised before junior dispatch.
