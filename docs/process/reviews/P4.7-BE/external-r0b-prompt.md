# P4.7-BE external R0-B prompt — dual-lens (admission/authz trust boundary ∥ spine no-regression)

**Slice**: P4.7-BE — plugin management endpoints (`GET /plugins`, `POST /plugins/{id}/enable·disable·admit`, `DELETE /plugins/{id}`). Realizes ADR-038 D5 (pinned-not-built) + lands ADR-039 D5 seam #2 / D9 authz. `requires_cross_family_review: true` (DP5). Boot-only config-file writes; admit = author-entry-only (no fetch); authenticated⇒allowed (no role check).

You are the cross-family external reviewer. Read the impl diff on the impl branch + the senior plan (`docs/process/senior-plans/P4.7-BE.md`) + the brief (`docs/process/architect-briefs/P4.7-BE.md`). Apply **both** lenses. The two lenses are orthogonal by design (`docs/process/dual-lens-r0b.md`): Lens A = "the endpoints are insecure / pierce admission"; Lens B = "the endpoints broke ADR-038/039's boot-only + spine." Report 🔴 (blocking) / 🟡 (architect-routable) / 🟢 (nit) with file:line evidence.

---

## Lens A — management-endpoint admission / authz trust boundary (the "endpoint done wrong" adversary)

Can any of the five endpoints:

1. **Admit unverified code / bypass the gauntlet (DP3a).** Does `admit` author the registry entry **only**, leaving the digest-before-extract gauntlet (`plugins/fetch.py:121-187`, digest-verified-BEFORE-extract `:170-181`) the unchanged, mandatory floor for fetched bytes? Is a digest-bearing operator-authored entry still required? The shape↔root / duplicate-id / `isinstance(enabled, bool)` validators (`provenance.py:282-355`) must stay the fail-closed floor — no endpoint path lowers the bar. Confirm `admit` does **not** synchronously fetch (DP1-i; coupling network fetch into the handler is out of scope and would be a finding).
2. **Act as an unauthenticated or wrong principal.** Are all five routes absent from `PUBLIC_PATHS` (`auth/middleware.py:36`) → `401` before the handler for an unauthenticated caller? Is the principal read **server-side** from `request.state.principal`, **never** the request body (ADR-039 D7, mirroring seam #1 `app.py:997-1005`)? Any body-supplied actor/user field is a forge finding.
3. **Accidentally land on the public allowlist.** A write endpoint exempted from auth (added to `PUBLIC_PATHS`, or a routing prefix that matches a public path) is a 🔴.
4. **Produce a malformed / refuse-all `config/plugins.yaml` (DP3b — the heart).** Does `write_plugin_registry` **round-trip the proposed mutation through `load_plugin_registry`'s validator BEFORE persisting**, write **atomically** (temp + `os.replace`), and **reject any write whose result would fail to parse** (→ would trip `REGISTRY_REFUSE_ALL` at boot, `loader.py:630` / `app.py:503-510`, disabling every plugin — a self-inflicted outage)? On a rejected write, is the pre-existing file **byte-unchanged** (no torn write, no temp leak)?
5. **Forge a shape↔root mismatch / provenance through the write path.** Can a write author an entry that forges provenance/posture (must be impossible — provenance is host-derived, never a registry field, `provenance.py:174-177`) or a fetched-shaped entry missing the source_url+digest pair (must be rejected by the round-trip, fail-closed)?

Also: is the **single-writer** discipline preserved (writes on `ctx.writer_executor`, max_workers=1 — no concurrent-write race on the file)? Is `plugin_subprocess_env` not echoed wholesale by `GET`?

## Lens B — spine-preservation / no-regression (the "did the endpoints break the constitution" adversary)

1. **Boot-only invariant preserved.** Do the writes mutate **only** `config/plugins.yaml` on disk and signal "effect next restart" — with **zero live mutation** of the running `AppContext` (no re-call of `load_plugins`, no rebuild of agents/tools/local_tools/mcp_sessions, no mid-turn `MCPSession` teardown — ADR-038 D2 "zero new runtime-mutation surface", `app.py:588-620`)? Any hot-reload / live-store snuck in is a 🔴 (it reverses an Accepted ADR-038 deferral, would require ADR-041).
2. **Validator byte-unchanged + write round-trips it.** Is `load_plugin_registry` (`provenance.py:230-366`) and its validator block (`:282-355`) **byte-unchanged**? Does the write path **round-trip through it** (not a parallel re-implementation of validation)?
3. **Gate untouched / no new `LLMPurpose`.** Does admission stay a **non-gated operator action** (ADR-038 DP2c — not routed through `decide_tier` / the autonomy gate)? `grep LLMPurpose` → zero new entries. `_execute_local_call` + `score`/`decide_tier`/`emit_gate_decision` byte-frozen (ADR-038/039 constitutional carry-forward).
4. **Existing routes + middleware + seam #1 unregressed.** Do `/login`·`/logout`·`/rooms*`·`/intent`·`/confirm`·`WS /stream` (`app.py:699-1006`) + `AuthMiddleware` + the realized seam #1 (`app.py:997`) still behave identically? Is the new `AppContext.config_dir` field **additive + default-valued** (existing test constructions still build)?
5. **Seam granularity correct.** Is the ADR-039 D5 **seam #2** comment planted on enable/disable, and a **separate finer seam** on `admit` (admit = higher-trust, introduces new fetched code) — so a future DP3b gates who-may-admit stricter than who-may-toggle? No actual role check is built (DP3b deferred).

---

**Orthogonality check**: Lens A is "insecure endpoint / pierced admission"; Lens B is "broke boot-only / spine". A finding that fits both is fine — note it under both. Anything you cannot tie to a file:line is a 🟢 at most.
