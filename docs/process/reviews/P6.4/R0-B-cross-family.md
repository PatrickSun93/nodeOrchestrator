---
task_id: P6.4
round: R0-B
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 1
---

# R0-B cross-family review — P6.4 (descriptive doc-pin: E+F egress residuals → ADR-037 D5)

## Lens preamble

This slice is a **descriptive doc-pin** — no behaviour change, no egress semantic change. The cross-family lens on a no-behaviour-change slice should over-correct for the risk that the inscription **misrepresents** the enforced surface (claiming a property the code doesn't enforce, or under-claiming a real limitation). The security question is: **does the ADR text + docstring truthfully describe what the code already does?** And the tripwire question: **does the F test actually pin fail-closed (i.e., would it FAIL if someone loosened the proxy)?**

The runtime-integration lens (cross-family's structural advantage over Claude-family per `dual-lens-r0b.md`) has less surface on this slice — there are no new call paths, no new failure modes. The audit is on inscription honesty.

---

## Findings

### 🟢 G1 — No egress behaviour change; inscription is honest; F pin correctly trips on loosening

**Surface**: `egress_proxy.py` (docstring only), `ADR-037-syscall-egress-sandbox.md` (D5 bullets + Amendment 2 note), `test_egress_proxy.py` (new `test_f_plain_http_fails_closed_405`).

**Evidence**:

1. **Zero executable code change in `egress_proxy.py`.** The `git diff` shows only the module docstring changed — the `_handle` method at `:138-141` (`parts[0].upper() != "CONNECT"` → 405) is byte-identical. The allowlist check at `:159`, the `_send_response`, `_relay`, `_serve` — all untouched. The proxy's CONNECT-only enforcement is unchanged.

2. **Zero `spawn.py` change.** `_create_network` at `spawn.py:226-230` still creates the bridge without `--internal`. No `--internal` flag was added. The sandbox network-creation mechanism is unchanged.

3. **Zero spine diff.** `git diff origin/main...origin/claude/P6.4-impl -- src/orchestrator/core/ src/orchestrator/autonomy/ src/orchestrator/llm/ src/orchestrator/rooms/` is empty. `_execute_local_call`, the autonomy gate, `LLMPurpose`, `run_pipeline`, COUNTDOWN spine — all untouched.

4. **Docstring correction is truthful.** The old docstring claimed `http(s): … → CONNECT` for both plain-http and https. The code at `:140-141` returns 405 for any non-CONNECT method — plain-http was never supported. The new docstring correctly separates https (CONNECT → tunnel) from plain http (absolute-form GET → 405 → fail-closed). The correction removes an over-claim; it does not introduce one.

5. **ADR-037 D5 E bullet is honest.** It states: the bridge is created without `--internal`; the CONNECT proxy is the enforcement; the residual is bounded by DNS-disabled + `--cap-drop=ALL` + `nobody` + operator-controlled image; `--internal` is withheld because it can break `host.docker.internal`→proxy reachability. All five claims are verified against the code: (i) `spawn.py:226-230` has no `--internal`, (ii) `egress_proxy.py:159-168` is the allowlist enforcement, (iii) `profile.py` sets `--dns 0.0.0.0` + `--cap-drop=ALL` + non-root user, (iv) the image is operator-provided via config, (v) the brief + senior plan both cite the R0-B's own conditional direction that `--internal` may break proxy reachability. The bullet neither under-claims (it acknowledges the bridge is internet-reachable via NAT) nor over-claims (it does not say the bridge is firewalled — it says the proxy is the enforcement). Honest.

6. **ADR-037 D5 F bullet is honest.** It states: the proxy is CONNECT-only; in-container urllib sends an absolute-form GET for `http://` → 405; the fetch fails closed (TOOL_FAILED, no exfil); https is unaffected; consistent with D4's fail-closed default. All claims verified: `egress_proxy.py:140-141` is CONNECT-only; the 405 response is a proper HTTP error → urllib raises → TOOL_FAILED via the existing exception path in `net_trust.py`; https uses CONNECT → bypasses the 405 branch. The bullet correctly frames this as a functional limitation, not a security hole. No over-claim.

7. **F pin test correctly trips on loosening.** `test_f_plain_http_fails_closed_405` sends `GET http://allowed.internal/ HTTP/1.1\r\nHost: allowed.internal\r\n\r\n` — the exact absolute-form GET that in-container `urllib` emits for a plain-http URL routed through `HTTP_PROXY`. The proxy's `_handle` at `:140` parses this as method=`GET` ≠ `CONNECT` → returns 405. The test asserts `b"405" in response`. If anyone loosens the proxy to forward non-CONNECT methods (the prohibited behaviour change — removing the `!= "CONNECT"` check or adding a pre-CONNECT GET handler), the response would change from 405 to something else → the assertion **FAILS**. The pin is correctly placed on the exact code path that enforces fail-closed. The test docstring explicitly documents this tripwire intent.

8. **ADR Amendment 2 note is honest.** It states "no behaviour change, no semantic change" and "descriptive doc-pin — `plan_has_adr=false`". Both statements are true — the only code changes are a docstring + a test, and the ADR text describes the already-shipped surface. The amendment note does not claim to fix anything or change any behavior. It correctly cites the P4.3 dual-lens as the source of both findings.

9. **Gates: full green.** `ruff check` passes on changed files. `ruff format --check`: 2 files already formatted. `mypy --strict src tests`: no issues in 310 source files. `pytest tests/sandbox/test_egress_proxy.py`: 8/8 passed (7 existing + 1 new F pin test, 4.39s).

---

## Synthesis

No findings to surface. This is a clean descriptive doc-pin. Three artifacts changed (ADR text, module docstring, one regression test), zero executable code changed. The cross-family lens confirms:

- **The enforced surface is unchanged** — the proxy is still CONNECT-only, the bridge is still without `--internal`, the spine is untouched.
- **The inscription is honest** — both E and F bullets truthfully describe the code's behaviour, bounded by the same defense-in-depth layers the code already enforces. Neither under-claims a real limitation nor over-claims a security property the code doesn't provide.
- **The F pin test is a correct tripwire** — it asserts 405 on the exact request urllib emits for plain-http; if the proxy is ever loosened to forward non-CONNECT methods, this test FAILS. The pin is on the correct code path (`egress_proxy.py:140-141`, the CONNECT-only check).

The one minor code-formatting change in `test_rw8_proxy_refuses_redirect_host` (multi-line → single-line assert) is cosmetic and consistent with the existing test style in the same file — not a finding.

**Verdict: clean.**
