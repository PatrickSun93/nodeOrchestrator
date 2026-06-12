---
task_id: P6.4
round: plan-vs-impl
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 7
---

# Review: P6.4 — plan-vs-impl

**Reviewer:** senior planner (Claude Opus 4.8, 1M context) in primary session
**Date:** 2026-06-12
**Artifact reviewed:** `origin/claude/P6.4-impl` @ `3fac69c` (`P6.4-1: inscribe E+F into ADR-037 D5 + correct egress_proxy docstring + pin F fail-closed`) — single atom / single commit. Diff vs `origin/main`: 3 files, +67 / −5.
**Plan:** `docs/process/senior-plans/P6.4.md` (`plan_has_adr=false`, descriptive doc-pin, dual-lens `requires_cross_family_review=true`).
**State context:** `.workflow/P6.4.yaml` at `awaiting_senior_plan_vs_impl, cycle: 1`. One prior override (architect, `awaiting_architect_accept → awaiting_junior_impl`: no-ADR-slice hook-transient correction — the recurring no-ADR gotcha, cf. P6.1/P6.2). State coherent with reality.

This is a **descriptive doc-pin** — the whole faithfulness question is **"does it inscribe what already ships and change zero egress behaviour?"** Answer: **yes, exactly.**

---

## Faithfulness to plan (the three plan pieces)

### G1 — (a) ADR-037 D5 ledger inscription (E + F) — FAITHFUL
Two bullets added to the D5 honest-residual list, one for **F** (plain-`http://` → 405 fail-closed) and one for **E** (per-call bridge without `--internal`), in the existing bullet style (bold lead-in + one honest sentence). Both carry an `(Inscribed P6.4)` tag; F points at its pinning test. Matches plan §2(a) bullet content and shape.

### G2 — (a) Amendment 2 audit note — FAITHFUL
`## Amendment 2 — P6.4 (D5 egress-residual inscription, 2026-06-12)` appended after Amendment 1, stating `plan_has_adr=false` / no Accept gate / same weight as A1-5, **no behaviour change / no semantic change**, and pointing at the two canonical D5 bullets. This is the audit-trail half exactly as plan §2(a) point 2 / §5 prescribed (A1-5 mirror: canonical D5 inscription + dated note).

### G3 — (b) egress_proxy docstring correction — FAITHFUL + STRICTLY BOUNDED
The over-claiming `- http(s): … → CONNECT <host>:<port>` line is replaced with a `Supported transports:` block that states `https` → CONNECT (tunnelled) and **plain http NOT supported → absolute-form GET → 405 → fail-closed (ADR-037 D4)**; the `ssh git_push` line is untouched. **Confirmed the change is docstring-only:** filtering the `egress_proxy.py` hunk for any executable line returns empty — `_handle`/`_serve`/allowlist/`_send_response`/the `405` branch are **byte-identical**. Honours plan §2(b) "strict bound: only the module docstring comment lines."

### G4 — (c) regression test `test_f_plain_http_fails_closed_405` — FAITHFUL, asserts real behaviour
Sends the exact absolute-form GET in-container `urllib` emits for a plain-`http://` URL (`GET http://allowed.internal/ HTTP/1.1\r\nHost: allowed.internal\r\n\r\n`) straight to the `EgressProxy` object (no Docker — the correct boundary the module already uses) and asserts `b"405"`. A small `_send_raw` raw-request sender was factored, exactly as plan §2(c) allowed. **Asserts genuinely-shipped behaviour:** verified `egress_proxy.py:142-143` on the impl branch — `if … parts[0].upper() != "CONNECT": _send_response(client, b"405 Method Not Allowed")` — so the 405 is real, the test will pass, and it is a true **fail-on-LOOSEN tripwire** (docstring spells out: MUST FAIL if the proxy is ever taught to forward non-CONNECT methods → that needs an ADR-037 D2 amendment + architect dispatch).

---

## Zero-behaviour-change / red-line discipline

### G5 — egress mechanism byte-frozen (the §5 red line held)
- `egress_proxy.py` executable body: **byte-identical** (only docstring touched — verified by hunk-filter).
- `spawn.py`: **not in the changeset** — `_create_network` untouched, **`--internal` NOT added** (E is *inscribed*, never *changed*). Plan §2-out-of-scope + §5 ⛔ honoured.
- No attempt to make plain-http work (that would LOOSEN egress = the prohibited F-behaviour-fix). The test is built to trip exactly that.

### G6 — no plan-external expansion
Only out-of-plan diff line is a **ruff-format auto-collapse** of an existing multi-line assert in `test_rw8_proxy_refuses_redirect_host` (its parenthesized form fits on one line under `line-length = 100`). This is inert gate-hygiene collateral from running `ruff format`, **not** a behaviour or scope change — acceptable. No other file, no new call path, no constitutional-spine touch (`_execute_local_call` / autonomy gate / `LLMPurpose` / `run_pipeline` / COUNTDOWN spine all absent from the diff), no new `LLMPurpose`.

### G7 — clean workflow hygiene
The reviewed diff contains **no stray `.workflow/` state-advance commit** (the recurring junior-self-advance gotcha) — `git diff --stat … -- .workflow/` is empty. Single atom = single commit as the plan prescribed.

---

## Verdict

**CLEAN.** The impl is a faithful, strictly-bounded realisation of the P6.4 descriptive doc-pin: E + F are inscribed into the D5 ledger with a dated Amendment-2 audit note (A1-5 weight), the egress_proxy docstring over-claim is corrected docstring-only, and F's fail-closed 405 is pinned by a fail-on-LOOSEN regression test asserting genuinely-shipped behaviour. **Zero egress semantic, mechanism, or code-path change; the §5 red line held; no plan-external expansion; spine byte-frozen.** No findings owed; no architect escalation required (no D2 touch, no new ADR, no routing question).

This is a same-family (senior) plan-vs-impl pass. The dual-lens (`requires_cross_family_review=true`) cross-family/security lens remains to confirm the inscription matches the enforced surface and no egress semantic moved — dispatched separately.
