---
review: R0-A
task_id: P4.2-B4
reviewer: architect-partner (in-family lens)
stage: impl
verdict: needs_architect
scope:
  - src/orchestrator/tools/net_trust.py (new — SSRF validator + resolve-then-pin transport)
  - src/orchestrator/tools/network_tools.py (new — web_fetch / web_search closures + registry)
  - src/orchestrator/tools/executor.py (per-pass network cap)
  - src/orchestrator/agents/selection.py (excerpt-exclusion for network tools)
  - src/orchestrator/api/app.py (composition root wiring)
  - docs/decisions/ADR-028 D3 amendment + ADR-031 D1a annotation
  - tests/tools/{test_net_trust,test_network_tools,test_executor,test_constitution}.py
baseline: origin/claude/P4.2-B4-impl @ f7d2909 (== local HEAD; merge-base origin/main b0c62f4); diff = the 7 commits B4-1,2,4,5,6,7,8
against: ADR-035 (Accepted 2026-06-05) + the constitution (tests/tools/test_constitution.py t1–t10)
findings:
  - id: Y1
    severity: needs_architect
    title: "redirect re-validation (a named SSRF-checklist item) is unit-tested only at handle_request level, not driven through httpx's live redirect loop"
  - id: Y2
    severity: alpha-lean
    title: "web_search provider-response parse (network_tools.py:236) can raise AttributeError on {\"web\": null} → generic local_tool_error instead of the D4 search_provider_error class"
informational:
  - "I1: B4-3 commit number absent — web_search folded into B4-2 (network_tools.py holds both closures); fully impl'd + tested; commit-granularity deviation from the planned atomic list only"
  - "I2: NAT64 / non-::ffff 4-in-6 embeddings not unwrapped by is_denied_ip — within the ADR D2/D3 residual (ii)/(iii), Accepted, P4.3-retired (R0-B checklist may probe)"
  - "I3: test_net_trust.py header says 'stubbed resolvers' but §5/t10b use the REAL getaddrinfo on numeric literals (no egress) — doc-string imprecision, no functional impact"
note: R0-B cross-family runs in parallel (impl-stage dual-lens, requires_cross_family_review=true); NOT read before this review. Synthesis is the architect's step. Gates verified locally (ruff + mypy --strict 242 files + full pytest, all green).
---

# R0-A (impl-stage) — P4.2-B4 (network local tools: `web_fetch` / `web_search`)

R0-A is mandatory at impl regardless of the parallel senior plan-vs-impl verdict (ADR-008 Amendment 1). I probed the SSRF + liveness spine against the ADR-035 carry-forward (§⭐⭐) and the standard SSRF-bypass checklist (D3-i). **No 🔴; no blocking issue.** The SSRF floor, resolve-then-pin, the B1 DNS-timeout fix, the credential-strip, the empty-executor-diff, `web_search`'s key-isolation, and both ADR amendments are all faithful and verify-cited below. Two 🟡 surface for routing (one test-depth on a load-bearing security property; one minor robustness), plus three 🟢 informationals.

State note: `.workflow/P4.2-B4.yaml` auto-advanced `awaiting_junior_impl → awaiting_senior_plan_vs_impl` mid-session (dev-harness machinery; the impl-stage review fan-out). Consistent with reality (impl pushed, reviews underway). Left uncommitted per dispatch (this commit adds **only** R0-A.md).

## What I verified (cite)

**SSRF floor — `is_denied_ip` (net_trust.py:40-63).** Deny-if-any over loopback/private/link-local/unspecified/multicast/reserved, with the two bypass classes the ADR D2 names explicitly: IPv4-mapped-IPv6 unwrapped-then-reclassified (`:47-48`, catches `::ffff:127.0.0.1`) and **CGNAT `100.64.0.0/10`** as an explicit check because `is_private` does not cover it (`:30,:54-56`; `100.100.100.200` Alibaba-metadata included — `is_private` would miss it). Metadata `169.254.169.254` falls under `is_link_local` (`:57`). t10a (test_constitution.py:742-785) + the parametrized floor (test_net_trust.py:31-78) assert all of these behaviorally, and that public IPs are allowed.

**Resolve-then-pin (net_trust.py:79-172).** `_resolve_and_validate` validates **all** resolved addresses (`:104-117`), raises `ssrf_blocked` if **any** is denied (`:112-115`), and pins the first routable IP (`:116-117`); the transport then connects to the **pinned IP literal** (`copy_with(host=pinned_ip)`, `:152`) — no re-resolve at connect, so TOCTOU/rebind cannot slip an internal IP through. TLS integrity is preserved via the `sni_hostname` extension (`:156-159`) so httpcore verifies the cert against the **original hostname** while connecting to the IP (`verify=True` always, net_trust.py:141; `t10c` forbids `verify=False`). The original `Host` header is preserved through the rebuild (`:164-168`). Deny-if-any and rebind-to-loopback/metadata are tested (test_net_trust.py:146-184). Worth noting the failure mode is safe even if `sni_hostname` were ever mishandled: the cert would verify against the IP and **fail closed** (TLS error → `fetch_failed`), never leak.

**🔴-FIX B1 — bounded DNS (net_trust.py:86-94).** `getaddrinfo` runs on a dedicated single-worker pool via `_DNS_EXECUTOR.submit(...).result(timeout=DNS_RESOLVE_TIMEOUT_S=5.0)`; on expiry → `future.cancel()` + `network_timeout`. The writer thread is bounded to ≤5 s per resolution even against a hung resolver (a leaked OS thread may persist until the kernel resolver's own timeout, but it only *returns data*, never writes the store — single-writer intact). This is the previously-unbounded single-writer term, now closed. test_bounded_dns_timeout (test_net_trust.py:251-265) proves the `network_timeout` path without hanging a real thread.

**Liveness terms all finite.** `retries=0` (net_trust.py:141; t10e asserts), granular `httpx.Timeout(connect=5,read=15,write=5,pool=5)` (network_tools.py:39), `max_redirects=5` (net_trust.py:198 / network_tools.py:45), and **streamed-bounded** read capped at `MAX_RESULT_BYTES` (`_stream_bounded` breaks mid-stream, network_tools.py:94-113) — no unbounded buffer, and a decompression bomb is cut at 64 KiB because iteration stops and the client closes. test_web_fetch_over_size_truncated (test_network_tools.py:142-158) confirms truncation + `output_truncated_at`.

**Credential-strip (net_trust.py:178-203).** `build_ssrf_client` sets `auth=None, cookies={}, headers={}` (`:200-202`); no orchestrator env/secret is read on this path. A cross-origin redirect cannot forward auth because none is set. web_fetch is GET-only (`content=b""`, `:169).

**Empty-executor-diff / t3b (executor.py).** The `git diff b0c62f4..HEAD` on executor.py is **purely additive**: the constant (`:53-58`), the counter (`:123`), the `_is_network` marker read (`:178-180`), and a **separate `elif _is_network` branch** (`:209-239`) mirroring the subprocess branch. `_execute_local_call` is **byte-unchanged** (no diff hunk touches it), and the AST guard t3b (test_constitution.py:190-231) asserts it references no decision symbol. The cap is mechanism-in-the-loop, not a decision-logic edit — t3b holds. The independence test (test_executor.py:756-800) drives 10 subprocess + 10 network calls in one pass → 20 results, 0 failures, proving the two caps are distinct resource budgets (ADR D4 / plan §5-2); the cap-exceeded path is tested too (test_executor.py:718-753 → `turn_network_cap_exceeded`).

**web_search (network_tools.py:176-253) — credential + SSRF-N/A posture.** Key is env-only (`BRAVE_API_KEY` or config `api_key_env`, `:181-184`), fail-closed when absent (`:191-192`), sent **only** in the `X-Subscription-Token` header to the **fixed** `_BRAVE_SEARCH_BASE_URL` (`:48,:211`) via **standard** `httpx.Client` (`:213`, correctly *not* the SSRF transport — fixed endpoint, SSRF N/A). The agent query rides as the `q=` param (`:210`), URL-encoded by httpx — it cannot escape into host/path, so there is no SSRF vector through search. `max_results` clamped to [1,20] (`:202-205`). test_web_search_api_key_only_in_brave_header (test_network_tools.py:305-336) asserts the key is in the header, **not** in params, **not** in output; 5xx → `search_provider_error` (`:224-227`); fail-closed tested (`:194-203,:386-395`). The key never reaches a fetched URL (web_fetch strips all headers; the key lives only in web_search's closure).

**Excerpt-exclusion (selection.py:105-147).** `_NETWORK_TOOL_NAMES` added (`:111-116`); the call_id filter now excludes network-tool `TOOL_CALL`s keyed on `tool_name` (`:145`), so open-web bytes stay out of the cross-agent `snapshot_excerpt` steering surface — raw `TOOL_RESULT`, not interpreted (no new `LLMPurpose`; t3 holds). Drift sync-test (test_constitution.py:652-671) pins `_NETWORK_TOOL_NAMES == build_network_tool_registry().keys()`; the canary test (`:674-734`) confirms exclusion + that trusted local results still render.

**Amendments match Accepted.** ADR-028 D3 strikes the network deferral with an inline `[Amended P4.2-B4 → ADR-035, Accepted 2026-06-05]` note in both the Status line and the deferred-tools paragraph; ADR-031 D1a is annotated "the NETWORK half of `RB-FS/NET` is now the ACTIVE (agent-chosen-URL) surface … same P4.3 retirement path." Both match ADR-035's Accepted scope. The composition root (app.py:242-254) loads `web_search.yaml` (absent → None → fail-closed) and composes `build_network_tool_registry` at the api/ root, keeping `local.py` pristine (t6); `config/web_search.yaml.example` commits the pattern, not the key.

**IP-literal-encoding (A3/Y3, the plan-stage routed item).** t10b (test_constitution.py:788-808) feeds `http://2130706433/`, `http://0x7f.0.0.1/`, `http://0177.0.0.1/` through the full transport on the **real** resolver (stubbed connection) and accepts `ssrf_blocked`/`fetch_failed`/`InvalidURL` — robust across platform resolver quirks, proving normalise-then-deny on the impl resolver rather than by assumption. CGNAT (A1) and CNAME-chain-to-internal (A2) have dedicated denial cases (test_net_trust.py:81-88,:192-207).

**Honest egress residual — stated truthfully.** The impl makes **no** claim to prevent data-exfil to a *public* attacker URL: there is no egress allowlist, and the IP floor permits public hosts by design. That is the **active** network half of `RB-FS/NET` (ADR-035 D2/D3-ii), Accepted exactly as ADR-031 D1a / ADR-034 D2 modelled it, with the excerpt-exclusion shrinking (not closing) the injection vector and P4.3 as the retirement. The code matches the inscription — no over-claim.

## Findings (architect routes; I do not)

**🟡 Y1 — redirect re-validation is a named SSRF-checklist item but only unit-tested at the `handle_request` level, not through httpx's live redirect loop.** The *code* is correct: `follow_redirects=True` + `max_redirects=5` on the client (net_trust.py:197-198) and `handle_request` re-runs scheme + resolve-then-pin on every invocation, and httpx follows redirects at the **Client** layer (re-invoking the transport per hop) — so a `302 → http://169.254.169.254` is re-validated and blocked. But the tests **simulate** that: test_redirect_to_internal_blocked (test_net_trust.py:278-294) calls `handle_request` directly with the post-redirect URL, and test_web_fetch_redirect_to_internal_ssrf_blocked (test_network_tools.py:174-186) mocks `client.send` to raise. Neither drives a real 302-chain through the live client to prove httpx re-enters our transport per hop. Given the notorious redirect-bypass history the ADR D3-i explicitly calls out, this load-bearing property rests on the httpx contract + architecture, not a test. It **is** testable without egress (inject a fake `self._inner` returning a 302 → the client follows → our `handle_request` re-validates the redirect target). **Lean α** (add one MockTransport-driven redirect-chain integration test) — cheap, closes a checklist item; **δ** is defensible (architecture + httpx contract is sound). R0-B (the cross-family SSRF prober) may corroborate. Architect: α or δ?

**🟡 Y2 — web_search provider-response parse can raise the wrong error class.** `data.get("web", {}).get("results", [])` (network_tools.py:236) raises `AttributeError` if Brave returns `{"web": null}` (key present, value None), and per-item `.get` assumes each result is a dict. These escape the `response.json()` try/except (`:229-234`) and fall to the executor's generic `except Exception` → `TOOL_FAILED(local_tool_error)` — **fail-closed, no security impact**, but a less precise class than the D4 result-semantics `search_provider_error:` family. **Lean α** (trivial: guard `web` is a dict / extend the existing try to cover the parse) or **δ** (accept; provider is operator-trusted, fail-closed is adequate for MVP). Low priority.

**🟢 I1 — B4-3 commit absent.** The plan listed B4-1..8 atomic; the branch has B4-1,2,4,5,6,7,8. `web_search` (likely earmarked B4-3) was folded into **B4-2** ("web_fetch closure + network registry"), whose new `network_tools.py` holds **both** closures. Functionality is complete + tested (test_network_tools.py §4-6). Commit-granularity deviation from the planned atomic list only — no scope/correctness impact. Noted for atomic-commit discipline.

**🟢 I2 — NAT64 / non-`::ffff` 4-in-6 embeddings.** `is_denied_ip` unwraps IPv4-mapped (`::ffff:0:0/96`) but not NAT64 (`64:ff9b::/96`) or other embeddings; a host with a NAT64 gateway + attacker DNS could in principle reach internal v4 via an address the floor doesn't classify denied. This sits squarely inside the ADR D2/D3 residual (ii)/(iii) ("exotic resolver/rebind edges + any range the denylist misses"), Accepted and P4.3-retired — consistent with the inscription, not a new finding. Flagged for the R0-B checklist.

**🟢 I3 — doc-string nit.** test_net_trust.py:1-4 says "All tests use stubbed resolvers or mocked transports"; §5 + t10b actually use the **real** `getaddrinfo` (numeric literals → local computation, no DNS egress). The "no real network egress" claim holds; "stubbed resolvers" is imprecise. Trivial.

## Gates (verified locally on f7d2909)

- **ruff**: `All checks passed!` (changed src + tests/tools).
- **mypy --strict** (canonical `files=[src,tests]`): `Success: no issues found in 242 source files`.
- **pytest**: full suite green (only a pre-existing Starlette/httpx testclient deprecation warning, unrelated to B4); the four B4 suites (`test_net_trust`, `test_network_tools`, `test_executor`, `test_constitution`) pass, including t1–t10.

**Verdict: `needs_architect`** — no 🔴, nothing blocking; route Y1 (α/δ) + Y2 (α/δ), with I1–I3 for the record. R0-B cross-family pending; synthesis is the architect's step.
