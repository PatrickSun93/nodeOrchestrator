---
task_id: P3.5
stage: plan
artifact: architect-routing-on-plan
routed_by: architect (Peidong), via orchestrator
date: 2026-06-03
reviews_routed:
  - R0-A-on-plan.md         # in-family (architect-partner): needs_architect (0R/3Y/3G)
  - R0-B-cross-family.md    # true cross-family (DeepSeek V4 Pro): blocking (1R/6Y/5G)
routing_summary: D4 posture A confirmed (A-now-B-later) + ALL findings α-absorb
absorbed_into:
  - docs/decisions/ADR-029-plugin-system-manifest-loader-code-trust.md
  - docs/process/senior-plans/P3.5.md
---

# Architect routing — P3.5 plan stage (ADR-029 + senior plan)

Two plan-stage reviews on `claude/P3.5-plan`: **R0-A-on-plan** (in-family,
architect-partner — `needs_architect`, 3🟡/3🟢) and **R0-B-cross-family**
(true cross-family, DeepSeek V4 Pro — `blocking`, 1🔴/6🟡/5🟢). The architect
routed all findings; this artifact is the signal for senior revision
(`awaiting_senior_revision`). **Headline: Posture A confirmed; all findings
α-absorb (no β/γ).** The dual-lens earned its keep — R0-B's R1 (ADR step
ordering) + Y4 (atomic merge) are runtime-sequencing findings the in-family
lens did not raise; R0-A's Y1 (`tool_impls` shadow) + R0-B's threat-model
cluster (Y1/Y3/Y5) converge on the same exposure from two angles.

## ⭐ D4 code-trust / isolation posture — RULED: **Posture A confirmed (A-now-B-later)**

The architect rules **Posture A** (in-process import; the `plugins/` dir =
operator-curation = trust) for the operator-curated local-dir MVP; **Posture B
(subprocess isolation) reserved for P3.7** (untrusted remote provenance — a
fetched plugin is not operator-placed, so curation no longer holds, and B's
killable subprocess restores both the isolation/env boundary and the D5 bound).

**Condition (R0-A Y2 / R0-B Y1/Y3/Y5): the Accept requires the PRECISE exposure
inscribed** — the architect Accepts the *real* surface, not a softened one. The
following are now inscribed in ADR-029 D4 (and were the routing's load-bearing
ask):

- **L1 — no technical isolation + zero credential/env protection.** In-process =
  full host privilege incl. full `os.environ` (every API key); the ADR-027 D4
  credential-indirection + scoped-env are **MCP-subprocess-only**, zero
  protection for in-process plugin code. (R0-B Y5 → α: trust-boundary section
  cross-references this.)
- **L1b — import-time code is ungated by construction.** `importlib` runs
  top-level code at boot before any gate/room/turn exists; curation is the only
  control. (R0-A §3.2 → inscribe.)
- **L2 — Posture A VOIDS (not "relaxes") ADR-028 D5's absolute per-turn liveness
  bound for the plugin-local path; server-wide blast radius.** D5's bound
  excluded local tools on a fast-by-construction premise that the 3 host
  builtins satisfy but arbitrary third-party code breaks; one buggy (not even
  malicious) curated tool blocks the `max_workers=1` writer for **every room**,
  no cap (excludes local), no kill (in-process). (R0-A Y2 + R0-B Y3 → α —
  reword "relaxes"→"voids"; distinguish "3 known-bounded closures" from
  "arbitrary third-party code.")
- **Retire the "as trusted as a file in `src/`" analogy** (R0-B Y1 / R0-A §3 → α):
  a category error on review-path — `src/` is review-gated (brief→plan→ADR→
  R0-A/R0-B→CI→merge), `plugins/` is operator-accepted-third-party with no
  mandatory review. Posture A **relocates** the trust gate from commit-time
  multi-role review to deploy-time operator curation; the operator assumes the
  review burden CI+R0-A/R0-B provide for `src/`.
- **A→B migration surface itemized** (R0-B Y6 → α, architect upgraded from the
  reviewer's β lean): `importlib`+`LocalToolFn` → subprocess protocol +
  subprocess-runner; `plugins/code.py` reworked. Noted in ADR-029's
  Reversibility table; P3.7 owns the migration (this MVP does not pre-build the
  abstraction).

R0-A and R0-B **independently concur** Posture A is the right MVP (R0-A §3:
"A is the right MVP… the decision is not the problem; the Accept needs the
precise exposure inscribed"; R0-B synthesis: "the design is correct but the
ADR's threat-model framing needs tightening"). The posture stands; the
absorption is honesty/precision, not a redesign.

## Findings routing (all α)

| # | Review | Sev | Finding | Route | Absorbed into |
|---|---|---|---|---|---|
| R1 | R0-B | 🔴 | ADR-029 D2 step ordering imports plugin code **before** collision-check (security sequencing) | **α** | ADR-029 D2 → validate→collision-check→load non-code→load code→cap→atomic merge; plan §3 + P3.5-3/4 |
| Y1 | R0-A | 🟡 | `tool_impls → local_tools` not collision-checked → shadow-bypass (host ToolMeta gates plugin impl, sandbox bypassed); HR#5/D6 self-violation | **α** | ADR-029 D6 + D2 step 3; plan P3.5-3 acceptance + P3.5-8 shadow test |
| Y2 | R0-A | 🟡 | Posture A L2 understates: **voids** D5 bound (server-wide), not "relaxes"; import-time ungated | **α** | ADR-029 D4 L2 + L1b (see above) |
| Y3 | R0-A | 🟡 | ADR D7-vs-D6 self-collision (demo "reuses facilitator" → refused) | **α** | ADR-029 D7 + plan P3.5-7 → distinct ids (`demo_facilitator`/`demo-research`) |
| Y1 | R0-B | 🟡 | "as trusted as a file in `src/`" = category error | **α** | ADR-029 D4 (analogy retired → operator-accepted-third-party-trust) |
| Y2 | R0-B | 🟡 | Advisory-cap default-0 ambiguity: every new plugin tool → HARD_CONFIRM; demo won't AUTO without host classification | **α** | ADR-029 D5 (default-0 explicit) + D7/P3.5-7 (host-side `tools.yaml` entry) |
| Y3 | R0-B | 🟡 | "host's own tools run unbounded" understates the categorical change (3 bounded closures → arbitrary code) | **α** | ADR-029 D4 L2 (categorical delta) |
| Y4 | R0-B | 🟡 | Atomic-merge discipline implicit → half-register risk | **α** | ADR-029 D2 step 7 + plan P3.5-3/-5 (per-plugin intermediate; atomic merge) |
| Y5 | R0-B | 🟡 | Posture A zero credential/env protection — trust-boundary section should cross-ref L1 | **α** | ADR-029 trust-boundary section (cross-ref to L1) |
| Y6 | R0-B | 🟡 | A→B migration surface unstated (reviewer lean β) | **α** (architect upgraded) | ADR-029 Reversibility table (itemized) |

**Green / clean notes** (R0-A N1–N3, R0-B G1–G5): no action; recorded for the
audit trail. G1 (gate/executor/MCP-client untouched) + G2 (autonomy-bypass
structurally prevented: impl-without-ToolMeta → `UnknownToolError`, no
`TOOL_CALL`, executor never sees it) are the cross-family's confirmation that
the empty-diff + sole-chokepoint invariants are real, not aspirational.

## Result

Senior absorbs all α into ADR-029 + `senior-plans/P3.5.md` (this revision pass),
re-commits both review files with `verdict: clean` (RC-10 verdict bump, citing
the absorption), and writes this routing artifact. **ADR-029 remains Proposed**
(RC-23-safe) pending the architect's Accept. P3.5-4 is **no longer blocked** (the
posture is ruled); its import-after-collision-check ordering is the
security-load-bearing invariant. Expected next: architect verifies → ADR-029
Accept → junior dispatch (P3.5-1..8 serial).
