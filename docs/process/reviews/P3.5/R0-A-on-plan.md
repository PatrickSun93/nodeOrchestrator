---
task_id: P3.5
review: R0-A-on-plan
stage: plan
reviewer: architect-partner
lens: >-
  R0-A (in-family). The dual-lens R0-B runs separately on the same surface
  (senior authored reviews/P3.5/external-r0b-prompt.md); Y1/Y2 below are exactly
  the third-party-code-execution failure modes that lens should independently
  hit — convergence would strengthen them.
date: 2026-06-03
artifacts_reviewed:
  - docs/decisions/ADR-029-plugin-system-manifest-loader-code-trust.md
  - docs/process/senior-plans/P3.5.md
verdict: needs_architect
findings:
  blocking: 0
  needs_architect: 3
  clean_notes: 3
note: >-
  3 Y findings routed; the plan + ADR are structurally strong and the spine
  carry-forward holds. Y1 (substantive — plant-bypass): the collision-check
  covers role/skill/tool(ToolMeta)/server but NOT the tool_impls -> local_tools
  namespace, so a plugin tool_impl named after a host builtin (read_file)
  silently shadows the sandboxed host impl yet gates via the host's existing
  ToolMeta = a real gate/sandbox bypass AND a violation of the ADR's own HR#5
  (never silently degrades) + D6 (fail-closed on collision). Y2 (D4 honesty):
  Posture A's L2 understates the regression — it voids ADR-028 D5's absolute
  per-turn liveness bound (which explicitly excluded local tools as fast),
  blast radius server-wide, not merely relaxes it; import-time plugin code is
  ungated-at-boot. Y3 (internal consistency): ADR D7 vs D6 self-collision (the
  demo "reuses facilitator" would be refused under fail-closed-on-collision).
  Independent D4 judgment: concur Posture A (A-now-B-later) for the
  operator-curated local-dir MVP, conditioned on Y2 inscribing the PRECISE
  exposure so the architect Accepts the real thing.
verdict_history:
  - at: plan-stage
    verdict: needs_architect
    by: architect-partner
---

# R0-A-on-plan — P3.5 (Plugin system: ADR-029 + senior plan)

## 0. Method (what I independently verified)

I wrote the P3.5 brief, so I review against intent — but I traced the code, not
the ADR's self-report (the P2.1/P2.2 fabricated-probe discipline; `dual-lens-r0b.md`
§RC-20). Three claims load-bearing for the verdict, verified at `origin/main`:

- **The executor's local path** — `tools/executor.py::_execute_local_call:308`
  is `impl = local_tools.get(tool_name)` → `impl(params)` (`:327`), synchronous,
  in-process, wrapped `try/except → TOOL_FAILED` (`:326–331`). **No timeout, no
  kill.** ✓ (load-bearing for Y1 + Y2).
- **Host builtins ARE gate-classified** — `config/tools.yaml` classifies
  `read_file`/`list_files`/`get_current_time` at `reversibility: 10` (→ `AUTO_EXECUTE`). ✓ (load-bearing for Y1).
- **ADR-028 D5's "absolute bound" excludes local tools by premise** — D5: *"the
  per-turn MCP cap does not apply to local tools (fast, no inline block)"* +
  *"+ the (negligible) local-tool time."* ✓ (load-bearing for Y2).

## 1. Verdict — `needs_architect` (3 Y; 0 🔴)

| # | Sev | Finding | Lean |
|---|---|---|---|
| **Y1** | 🟡 | `tool_impls → local_tools` namespace is **not** collision-checked → a plugin shadows a host builtin (`read_file`) and gates via the host's ToolMeta → gate/sandbox bypass; innocent name-clash silently shadows. Violates HR#5 + D6. | **α absorb now** (cheap; closes a real bypass; delivers the ADR's own invariant) |
| **Y2** | 🟡 | Posture A's **L2 understates** the regression: it *voids* ADR-028 D5's absolute per-turn liveness bound (server-wide blast radius), not "relaxes"; import-time code is ungated-at-boot. | **α absorb into ADR D4** (inscribe the precise exposure; posture choice itself stands) |
| **Y3** | 🟡 | ADR **D7 vs D6** self-collision: the demo "reuses role `facilitator`" → refused under fail-closed-on-collision → the demo fails its own acceptance. | **α** (demo ships distinct ids — plan §5(2)(a); land it in ADR D7 + the demo) |

The constitutional spine carry-forward is **structurally sound** (§2); the D4
posture is **defensible and I concur** (§3), conditioned on Y2.

## 2. Constitutional spine carry-forward (brief §⭐⭐) — HELD

Structurally the strongest part of the plan, and it survives tracing:

- **Plugin tools route through the existing gate, unchanged.** A plugin tool's
  `ToolMeta` merges into the same `tools: dict[str,ToolMeta]` that flows
  `process_tool_calls → emit_gate_decision`; unclassified → `UnknownToolError`
  → refused (ADR-006). No second decision surface. ✓
- **Empty-gate-diff AND empty-executor-diff.** The plan extends the ADR-027 D2 /
  ADR-028 D6 empty-diff invariant to the executor (P3.5-5 acceptance: a grep/diff
  on `process_tool_calls`/`score`/`decide_tier`/`emit_gate_decision`/`tools/executor.py`/`mcp/`
  must be empty). I verified this is *achievable*: `_execute_local_call` needs no
  edit because plugin impls are just `LocalToolFn` (`Callable[[dict],LocalToolOutput]`,
  `executor.py:53`) values in `local_tools` — the executor already dispatches them.
  The "no executor edit" claim is real. ✓
- **No new `LLMPurpose`; load is code, not judgment.** The `plugins/` constitution
  test (P3.5-6, AST-modeled on `tests/tools/test_constitution.py`) forbids
  `decide_tier`/`emit_gate_decision`/`score`/`gate`/`select_model_and_provider`
  + any `llm/` provider call + asserts the frozen purpose set. The forcing
  function (P3.5 §4 "non-vacuous") is named. ✓
- **Trust boundary carry ADR-027 D4** (brief §⭐) — D5 reuses `api_key_env` +
  scoped-env *verbatim* (bind-not-restate); the plugin `mcp_servers` block IS the
  allowlist entry (presence = opt-in). Consistent with the ruled posture. ✓

**Caveat that becomes Y1:** the spine holds *for the four declaration surfaces*
(role/skill/tool-ToolMeta/MCP-server) because P3.5-3 collision-checks them
pre-merge. It does **not** hold for the **fifth** surface — `tool_impls → local_tools`
— which P3.5-3 defers to P3.5-4, and P3.5-4 does not collision-check. That is the
one place a plugin reaches the executor without passing the gate honestly.

## 3. ⭐ Independent judgment on the D4 code-trust posture (the headline)

**I concur with Posture A (A-now-B-later) for the operator-curated local-dir
MVP** — the senior's reasoning is honest and the architecture is consistent —
**conditioned on Y2.** My independent read:

**What the senior got right.** L1 (in-process = no privilege boundary; security
rests on curation) and L2 (in-process can't be timeout-killed) are **named, not
implicit** — the ADR-028 D3 "name the boundary so the dual-lens reads a posture,
not an oversight" discipline, applied. The sharp observation that **Posture B
(subprocess) ≈ "bundle an MCP server"** (which P3.4 already supports) is correct
and decisive: subprocess-isolating plugin code converges with the existing
`mcp_servers` path, so B's marginal value for *in-process convenience* is thin,
and **A-now-B-later mirrors ADR-027's stdio-local-now / remote-later** — when
provenance becomes untrusted (P3.7 remote/registry), B is the required posture.
That is a coherent, precedent-aligned trust architecture.

**Where my independent judgment diverges (→ Y2).** The Accept the architect is
being asked for is **heavier than the ADR's framing suggests**, on two points
the ADR currently softens:

1. **L2 is not "relaxes the D5 bound" — it VOIDS it for the local path, with a
   server-wide blast radius.** ADR-028 D5's *absolute* per-turn bound is real
   only because it **excludes local tools on the premise they are "fast, no inline
   block"** — a premise true for 3 host builtins written to that discipline
   (read_file is bounded *specifically* to avoid OOM-ing the single writer — D5 /
   `tools/local.py:8`). Admitting third-party code into `local_tools` **breaks the
   premise**: a runaway/blocking plugin tool (an accidental `while True`, a slow
   synchronous `requests.get`) blocks the `max_workers=1` writer — **every room's
   writes, not its own** — indefinitely, with **no cap** (the cap excludes local)
   and **no kill** (in-process). The ADR says "the host's own local tools already
   run in-process unbounded" — true of the *mechanism*, but it elides that D5's
   *bound* leaned on those tools being fast-by-construction. The honest Accept is:
   *Posture A voids ADR-028 D5's per-turn liveness guarantee for the plugin-local
   path; one buggy (not even malicious) curated tool is a server-wide DoS.*
2. **Import-time code is ungated by construction.** The gate is a tool-**call**
   chokepoint; `importlib`-ing a plugin module (P3.5-4/-5, at bootstrap) runs its
   top-level code **before any gate/room/turn exists**. Presence = opt-in (D5)
   therefore means *every* plugin in `plugins/` runs its import-time code at boot,
   full host privilege, curation the *only* control. D4 L1 says "loaded = runs …
   import time" — make explicit that **no gate covers it** (not a gap to fix — a
   property to disclose at Accept).

**The "as trusted as a file under `src/`" analogy** is accurate on *privilege*
(both in-process, full host) but not on *path*: `src/` passes brief → plan → ADR
→ R0-A/R0-B → merge; `plugins/` does not. Posture A **relocates the trust gate
from commit-time multi-role review to deploy-time operator curation.** Legitimate
— but the architect should Accept that the project's review chain does **not**
cover plugin code, so operator-curation must substitute equivalent rigor (the
same dependency as Y2.1's "treat curated plugin code with src/-grade care").

**Net:** A is the right MVP. The decision is not the problem; the *Accept needs
the precise exposure inscribed* (Y2) so it is an informed one. Y1 is **posture-
independent** — it must be fixed under A or B alike.

## 4. Findings (detail)

### Y1 🟡 — `tool_impls → local_tools` shadow gap (plant-bypass + HR#5 self-violation)

**Where:** ADR-029 D6 (collision policy enumerates "role / tool name / skill id /
server name" — **not** `tool_impls`/`local_tools`); plan P3.5-3 (collision-checks
"role/skill/tool/server", `tool_impls` deferred) + P3.5-4 ("resolve `<module>:<callable>`,
validate `LocalToolFn`-shaped, register" — **no collision-check stated**).

**The bypass (traced):** a malicious/buggy plugin declares **only**
`tool_impls: {read_file: "evil:read_file"}` and **no** `tools` ToolMeta.
- P3.5-3's collision-check runs on the *ToolMeta* namespace → the plugin added no
  ToolMeta → **no collision detected**.
- P3.5-4 merges the impl into `local_tools` → shadows the host's sandboxed
  `read_file` (`local_tools.get` is a plain dict lookup, `executor.py:308`).
- At call time the gate scores `read_file` via the **host's** ToolMeta
  (`tools.yaml` rev=10 → `AUTO_EXECUTE`) → `TOOL_CALL` → `_execute_local_call`
  runs the **plugin's** impl → bypasses the path-sandbox + OOM-guard
  (`tools/local.py` trust boundary) entirely.

**Why it's not merely a malicious-only concern:** an *innocent* plugin naming a
tool `read_file`/`get_current_time` silently shadows a host builtin — a
correctness bug regardless of trust, and a direct violation of the ADR's own
**HR#5** ("never silently degrades into a half-wired state") + **D6** (fail-closed
on collision). **Both merge directions are unsafe** without a check: plugin-wins →
host shadowed (bypass); host-wins → plugin tool silently dropped (silent degrade).
So the fix is a collision-check, not a merge-order choice.

**Fix (lean α):** D6 + P3.5-3/-4 collision-check `tool_impls` names against (i) the
host `local_tools` keys (`build_local_tool_registry`, `tools/local.py:131`), (ii)
the host `tools` registry, and (iii) cross-plugin `tool_impls`; **fail-closed on
any clash** (refuse that plugin, host registries unmodified). Add a discriminating
test: a plugin `tool_impl` named `read_file` → refused, host impl unchanged.

### Y2 🟡 — Posture A L2 understates the regression (D5 bound voided, server-wide)

Covered in §3.2. **Fix (lean α, into ADR D4):** restate L2 as *"Posture A voids
ADR-028 D5's absolute per-turn liveness bound for the plugin-local path (the cap
excludes local tools on a fast-by-construction premise plugin code breaks);
blast radius is the whole writer = every room; mitigation under A is the trust
model + documentation only (in-process is unkillable), and **Posture B restores
the bound** (killable subprocess) — the operative reason B is the required
posture once provenance is untrusted."* Add the import-time-ungated disclosure
to L1. (No code change — an honesty/Accept-precision fix; the posture stands.)

### Y3 🟡 — ADR D7 vs D6 self-collision (the demo would be refused)

ADR D7 says the demo "reuse[s]" role `facilitator` + skill `research-decomposition`
(core names). Under D6 fail-closed-on-collision, a plugin re-declaring a **core**
name is refused → the demo (P3.5-7) fails its own acceptance ("no collision with
core"). The plan §5(2) **catches this** and leans "(a) ship distinct ids" — the
right call — but the ADR D7 wording still says "reused facilitator." **Fix (α):**
the demo ships distinctly-named content (e.g. `demo_facilitator`); land the
distinct-id requirement in ADR D7 + the demo design. (Do **not** carve out
"core re-export ≠ collision" — it adds policy surface to a deliberately-loud MVP.)

## 5. Clean notes (no action; recorded for the audit trail)

- **N1 — `LocalToolFn`-shape validation is necessarily load-time-callable + call-time-fail-closed.** P3.5-4's "validate it is a `LocalToolFn`-shaped callable" can only check *callable* at load (return-type can't be checked without calling); a plugin impl returning a non-`LocalToolOutput` raises when the executor reads `output.content` → caught → `TOOL_FAILED` (`executor.py:326`). The plan relies on the inherited per-call fail-closed — correct; just confirm the impl doesn't claim more validation than is possible.
- **N2 — `min_host_contract`** (plan §5(3)): a `PLUGIN_HOST_CONTRACT_VERSION = 1` constant in `plugins/` is the right home. Fine.
- **N3 — dependency fail-closed** (D6): `model_ids`/`room_types`/`min_host_contract` unmet → refused, per-plugin isolated. Verified consistent with the loaders' inputs (`load_agents(..., models=)`; host room types). Clean.

## 6. What the architect rules (routing asks)

1. **Y1** — α absorb now? (lean yes — a real bypass + the ADR's own HR#5; cheap).
2. **Y2** — α absorb into ADR D4 (inscribe the precise L2/import-time exposure)?
   The **posture itself (A, B, A-now-B-later)** is the architect's Accept on
   ADR-029 — my independent lean is **A-now-B-later**, informed by the real
   exposure. (Y2 is about *honesty of the Accept*, not re-litigating the posture.)
3. **Y3** — α (demo distinct ids)? (lean yes).

Once routed, the senior absorbs (RC-10 verdict bump) and the **P3.5-4 code-loading
atomic stays blocked** on the D4 posture Accept (plan §3). R0-A is in-family; the
**dual-lens R0-B** should independently re-probe Y1 (gate/sandbox bypass) + Y2
(in-process liveness) on the same surface — I expect convergence.
