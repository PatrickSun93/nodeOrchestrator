---
task_id: P3.5
round: R0-B-cross-family
reviewer_family: deepseek
reviewer_model_id: deepseek-v4-pro
reviews_acked:
  - architect-briefs/P3.5.md
  - senior-plans/P3.5.md
  - decisions/ADR-029-plugin-system-manifest-loader-code-trust.md
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 12
note: >
  YAML frontmatter note uses block scalar to avoid colon-in-value parse failures.
  This is a plan-stage true-cross-family R0-B (DeepSeek V4 Pro) per
  dual-lens-r0b.md. The architect ruled requires_cross_family_review=true for
  P3.5 (admit-plugin-code-now — the project's largest security surface to date).
  Verdict bumped blocking -> clean (RC-10): R1 + all 6 Y alpha-absorbed per
  architect-routing-on-plan.md (architect 2026-06-03 via orchestrator).
verdict_history:
  - verdict: blocking
    at_commit: 122a8d0
    findings_count: { red: 1, yellow: 6, green: 5 }
    note: R1 ADR D2 step-ordering (code import before collision-check) + 6 Y threat-model/atomic-merge/migration
  - verdict: clean
    at_commit: post-routing-revision (this commit)
    findings_count: { red: 0, yellow: 0, green: 12 }
    note: >-
      R1 + Y1-Y6 all alpha-absorbed into ADR-029 + senior-plans/P3.5.md;
      Posture A confirmed (A-now-B-later) with full exposure inscribed.
      See architect-routing-on-plan.md.
  - verdict: clean
    at_commit: 7bec33d (impl-stage)
    findings_count: { red: 0, yellow: 0, green: 7 }
    note: >-
      Impl-stage dual-lens R0-B (DeepSeek V4 Pro). All 7 probe areas verified
      against origin/claude/P3.5-impl @ 7bec33d. R1 (collision-before-import),
      shadow-bypass, Posture A L1/L1b/L2 honesty, atomic merge, fail-closed,
      reversibility cap, constitution all confirmed in code + tests. Zero
      findings — clean design execution. See Impl-Stage Review § below.
---

# P3.5 R0-B cross-family review (plan + ADR-029)

> **RC-10 — frontmatter as live signal: `blocking → clean`.** R1 (🔴) + all 6 Y
> α-absorbed (architect routing 2026-06-03 via orchestrator;
> `architect-routing-on-plan.md`); senior revised ADR-029 + `senior-plans/P3.5.md`
> in this commit. Reclassified → 🟢 (absorbed):
> - **R1 (D2 step ordering)** → 🟢: ADR-029 D2 reordered to validate → **collision-check**
>   → load non-code → load code → cap → atomic merge; import-time code runs only
>   after the fail-closed gauntlet (matches the plan's safe atomic order).
> - **Y1 (`src/` analogy = category error)** → 🟢: ADR-029 D4 retires the analogy →
>   operator-accepted-third-party-trust (review-path distinct from `src/`).
> - **Y2 (default-0 ambiguity)** → 🟢: ADR-029 D5 — unclassified plugin tool → 0 →
>   `HARD_CONFIRM`; demo ships a host-side `tools.yaml` classification to AUTO.
> - **Y3 (host-tools-unbounded understatement)** → 🟢: ADR-029 D4 L2 — categorical
>   delta ("3 known-bounded closures" → "arbitrary third-party code").
> - **Y4 (atomic-merge implicit)** → 🟢: ADR-029 D2 step 7 + plan P3.5-3/-5 —
>   per-plugin intermediate; atomic merge; never half-registers.
> - **Y5 (credential/env scope)** → 🟢: ADR-029 trust-boundary section cross-refs L1
>   (credential-indirection/scoped-env are MCP-subprocess-only; zero for in-process).
> - **Y6 (A→B migration surface)** → 🟢: ADR-029 Reversibility table itemizes the
>   migration (importlib→subprocess; LocalToolFn→runner; `plugins/code.py` reworked).
>
> Original finding bodies preserved below as audit trail (the 🔴/🟡 markers are
> historical). G1–G5 confirmations (empty-diff + autonomy-bypass structurally
> prevented) stand.

## Lens preamble

This is a **true cross-family** R0-B (DeepSeek V4 Pro) at plan stage. The P3.5
slice admits third-party executable Python code into the orchestrator process —
the project's largest security surface to date. The cross-family lens is
dispatched precisely because in-family passes structurally under-probe
runtime-integration failure modes: import-time-vs-validation ordering,
half-register atomicity, and whether "fail-closed" claims hold against malicious
(not merely accidental) inputs.

**Bias I'm over-correcting**: the ADR and plan were authored in-family (senior +
architect). In-family reviews trust that "if the types are right, the runtime is
right." I'm probing the runtime failure paths: what executes when, what state is
mutated before a refusal, and whether the named limits on Posture A are honestly
bounded or systematically understated.

**Correction-mode note (RC-20)**: no in-family R0-A exists yet at plan stage, so
this review adds net-new findings only.

---

## Findings

### 🔴 Red (blocking — must be resolved before junior dispatch)

**R1 — ADR-029 D2 step ordering imports plugin code before collision-check
(security sequencing bug)**

- **Location**: `docs/decisions/ADR-029-plugin-system-manifest-loader-code-trust.md`,
  D2 steps 3–4 (lines ~63–66); cf. `docs/process/senior-plans/P3.5.md` P3.5-3/4
  atomic ordering (lines ~42–53)
- **What**: ADR-029 D2 orders: step 2 (validate manifest + dependencies) → step 3
  (load each surface, **including the new D4 code-loading mechanism** which
  `importlib`s the plugin module — top-level code executes at import time) →
  step 4 (collision-check + reversibility-cap + merge). Under Posture A,
  `importlib` runs the module's top-level code with full host privilege
  **before** the collision check in step 4. If two plugins both contribute
  `tool_impls.echo`, both modules are imported (arbitrary code executes) before
  the loader detects the collision and refuses them. The malicious code already
  ran.
- **Why it matters**: The ADR is the inscribed contract — junior reads it first
  (plan §1: "The design is inscribed in ADR-029 — read it first; this plan
  implements it"). If junior follows the ADR's step ordering literally, import-time
  code execution precedes collision detection. The plan's atomic ordering
  correctly puts P3.5-3 (collision-check) before P3.5-4 (code loading), but the
  ADR is the binding artifact that P3.7 and future developers will reference.
  The ADR's step ordering must be corrected to: validate → **collision-check**
  → load non-code surfaces → load code → cap → merge. The collision check must
  precede any code import.
- **Architect-partner lean**: α absorb — amend ADR-029 D2 step ordering to match
  the plan's safe sequence (collision-check before code import). The plan's
  ordering is correct; the ADR must reflect it.

### 🟡 Yellow (needs architect attention)

**Y1 — "As trusted as adding a file to src/" is a category error**

- **Location**: ADR-029 D4 (line ~83), echoed in plan §5(1)
- **What**: The ADR frames Posture A's trust model as "A local plugin is exactly
  as trusted as adding a file under `src/orchestrator/tools/`." This is a
  category error. `src/` files are version-controlled, reviewed (R0-A +
  plan-vs-impl + CI gates), and authored by known project contributors. A
  `plugins/` file is operator-placed with no mandatory review process, no CI
  gate, and no authorship provenance. The two trust models differ in review
  surface, not just directory location. The ADR should acknowledge this
  distinction rather than equating them.
- **Why it matters**: The analogy is load-bearing for the Posture A argument. If
  the architect accepts Posture A based on "it's the same as src/," they're
  accepting a weaker trust model than they may realize. The operator-curation
  boundary is real but qualitatively different from the src/ review boundary.
- **Architect-partner lean**: α absorb — reword the analogy to "A local plugin
  is operator-curated, analogous to but distinct from src/'s review-gated trust
  model. The operator assumes the review burden that CI + R0-A/R0-B provide for
  src/."

**Y2 — Advisory cap default-0 means every new plugin tool is HARD_CONFIRM by
default; demo tool won't AUTO_EXECUTE without explicit operator classification**

- **Location**: ADR-029 D5 ("host-authoritative-or-default-0"), plan P3.5-3
  acceptance
- **What**: The advisory cap compares plugin-claimed reversibility against a
  host-authoritative value, taking the minimum. For a tool the host has never
  classified (a new plugin tool), there is no host-authoritative value — the
  default is 0 (ToolMeta.reversibility default). Every genuinely-new plugin tool
  therefore defaults to reversibility 0 → HARD_CONFIRM → never AUTO_EXECUTEs.
  The demo plugin's executable tool (P3.5-7) would never reach the executor
  unless the operator adds a host-side `tools.yaml` entry raising the cap. The
  ADR and plan do not clarify whether "unclassified" means "use plugin's claimed
  value" or "default to 0." The former allows new tools to work; the latter
  requires operator reclassification for every new plugin tool.
- **Why it matters**: If default-0 is the intended posture, the demo must
  include a host-side classification entry, and the plan must state this. If
  "unclassified → use plugin's claimed value" is intended, D5 must say so
  explicitly. The current text is ambiguous on a point that determines whether
  any new plugin tool can ever AUTO_EXECUTE.
- **Architect-partner lean**: α absorb — clarify in ADR-029 D5: does an
  unclassified new plugin tool default to 0 (conservative, operator must
  classify) or use the plugin's claimed value (permissive, capped only against
  an existing host classification)? The demo's executable tool must be
  consistent with the ruling.

**Y3 — L2 risk widening: "host's own local tools already run in-process
unbounded" understates the categorical change**

- **Location**: ADR-029 D4 L2 (lines ~78–79), plan §5(1)
- **What**: The ADR frames Posture A's D5 liveness-bound relaxation as
  consistent with existing behavior: "the host's own local tools already run
  in-process unbounded (D5 bounds MCP via subprocess-kill; local tools are 'fast
  + bounded by assumption')." But the host's 3 builtins (`get_current_time`,
  `read_file`, `list_files` in `tools/local.py:131-140`) are hard-coded
  closures: no network, no subprocess, no infinite-loop surface, sub-ms to ms
  execution time. A third-party plugin tool has **none** of these guarantees —
  it can call `time.sleep(3600)`, open sockets, or `while True: pass`. The risk
  profile changes categorically from "3 known-bounded closures" to "arbitrary
  third-party code." The ADR's framing understates this.
- **Why it matters**: The architect's Posture A Accept decision should be made
  with an accurate understanding of the risk delta. The ADR's current framing
  suggests continuity with existing behavior when the change is categorical.
- **Architect-partner lean**: α absorb — amend L2 to distinguish "host's 3
  known-bounded, no-network/no-subprocess closures" from "arbitrary third-party
  code with no execution-time guarantees."

**Y4 — Atomic merge discipline not explicit: half-register risk if P3.5-3
eagerly merges into host registries**

- **Location**: Plan P3.5-3, P3.5-4, P3.5-5 (execution order); ADR-029 D2 step 4
- **What**: The plan splits plugin loading across three atomics: P3.5-3 loads
  non-code surfaces + collision-checks, P3.5-4 loads code, P3.5-5 merges into
  `_build_context`. If P3.5-3 eagerly merges into the host registries (rather
  than into a per-plugin intermediate `PluginLoadResult`), and P3.5-4
  subsequently fails (code import error), the plugin is half-registered: its
  roles, skills, tool ToolMetas, and MCP config are live in the host, but its
  code failed to load. The plan says P3.5-3 "produces the merged
  PluginLoadResult" but does not explicitly state that the merge into host
  registries is deferred to P3.5-5. Without this discipline, the half-register
  invariant (HR#5: "never partially-registers") is implementation-dependent.
- **Why it matters**: HR#5 is non-negotiable constitutional. The atomic merge
  discipline (per-plugin intermediate → validate all surfaces → then merge) must
  be explicit in both ADR and plan so junior doesn't eagerly merge.
- **Architect-partner lean**: α absorb — add explicit language to ADR-029 D2
  and plan P3.5-3/5: "P3.5-3 and P3.5-4 accumulate contributions into a
  per-plugin intermediate result; P3.5-5 atomically merges the complete result
  into the host registries. A failure at any stage discards the entire
  per-plugin intermediate — host registries are never mutated by a
  partially-loaded plugin."

**Y5 — Posture A offers zero credential/env protection for in-process code;
this is stated in L1 but the trust-boundary section should cross-reference it**

- **Location**: ADR-029 D4 L1, trust boundary section (lines ~29–30), D5
- **What**: The ADR's trust boundary section prominently features
  `api_key_env` credential-indirection (carried forward from ADR-027 D4) and
  scoped subprocess env. Under Posture A, plugin code runs in-process with full
  `os.environ` access — the credential-indirection mechanism provides exactly
  zero protection against in-process plugin code. L1 states "full host privilege
  (FS, network, env)" which covers this, but the trust-boundary section's
  prominent placement of credential-indirection without an adjacent note that
  "this applies to MCP-subprocess only; in-process plugin code (Posture A) can
  read all environment variables directly" creates a misleading impression of
  defense-in-depth that doesn't exist for the in-process path.
- **Why it matters**: A reader scanning the trust-boundary section (as
  implementers and future plugin authors will) sees layered defenses
  (allowlist + credential-indirection + scoped-env + fail-closed). Without the
  cross-reference to L1, they may not realize that half these defenses are
  MCP-subprocess-only and don't apply to in-process plugin code under Posture A.
- **Architect-partner lean**: α absorb — add a one-line cross-reference in the
  trust-boundary section: "The credential-indirection and scoped-env mechanisms
  apply to the MCP-subprocess boundary only; under Posture A (in-process),
  plugin code has full environment access per D4 L1."

**Y6 — Posture A→B migration surface unstated**

- **Location**: ADR-029 D4, reversibility table (D4 row)
- **What**: The ADR defers Posture B to P3.7 (untrusted remote install) and
  notes the D4 reversibility cost as "Medium-High." But it doesn't enumerate
  what changes: the in-process `importlib` + `LocalToolFn` registration must be
  replaced with a subprocess protocol (the MCP pattern, or similar). The
  `plugins/code.py` module built for Posture A would need substantial rework or
  replacement. The reversibility table says "moving in-process (A) → subprocess
  (B) is a real execution-model change" but doesn't itemize the migration
  surface. This matters because P3.5 builds the `tool_impls` loading mechanism
  now — if Posture B is the eventual target for P3.7, the current mechanism
  should be designed with that migration in mind (e.g., a `ToolImplLoader`
  protocol that can be swapped).
- **Why it matters**: Without designing for the A→B migration now, P3.7 will
  need to either rewrite the code-loading path or maintain two parallel
  mechanisms. A protocol/abstraction at the loader level is cheap now and
  expensive later.
- **Architect-partner lean**: β defer — the architect may accept the migration
  cost as P3.7's problem. But the ADR should at least note the specific
  migration surface (importlib→subprocess protocol; LocalToolFn→subprocess
  runner) in the reversibility table.

### 🟢 Green (advisory — no action required)

**G1 — Gate/executor/MCP-client genuinely untouched** —
Verified against `origin/main`: `process_tool_calls` keys on `tools: dict[str,
ToolMeta]`, `_execute_local_call` keys on `local_tools: dict[str, LocalToolFn]`,
MCP client uses `mcp_sessions`. Plugin contributions merge into these same dicts
at `_build_context` — zero changes needed to the decision surfaces. The
"empty-diff" invariant is real, not aspirational.

**G2 — Autonomy bypass is structurally prevented** —
A plugin contributes both a ToolMeta (gate) and a LocalToolFn (executor) —
two distinct registries gated independently. `process_tool_calls` checks the
`tools` dict before appending a `TOOL_CALL` event; the executor only runs on
`TOOL_CALL` events (sole-appender guarantee per ADR-028 D6 t4). A plugin that
contributes only a LocalToolFn (no ToolMeta) cannot reach execution: the gate
raises `UnknownToolError` → `process_tool_calls` records
`refusal_reason="unknown_tool"` → no `TOOL_CALL` appended → executor never sees
it. The gate is the sole chokepoint. Adversarial probe exhausted.

**G3 — Constitution test design is well-specified** —
P3.5-6's constitution test (forbidding `decide_tier`/`emit_gate_decision`/
`score`/`gate`/`select_model_and_provider`, forbidding `llm/` provider calls,
asserting no new `LLMPurpose`) mirrors ADR-028 D6's `tests/tools/
test_constitution.py` pattern. The five assertions are specific and
non-vacuous. The `plugins/` package stays a pure data/config loader.

**G4 — Fail-closed dependency/collision posture is the correct conservative
default** —
D6's fail-closed-on-collision (plugin with conflicting name → refused) is the
loudest, safest MVP posture. Per-plugin load isolation (one bad plugin doesn't
block siblings) is correctly specified at the loader level (refuse-and-continue,
not crash-bootstrap). Namespacing (`<plugin>__<id>`) is correctly deferred as an
additive relaxation.

**G5 — Five-surface demo scope is appropriate** —
P3.5-7's demo exercising roles + skills + tools + MCP + executable code proves
the integration point's value (the bundle merge across all surfaces). Mirroring
P3.4's single-demo-connector pattern is consistent. The broken-variant test
(import error / raise → fail-closed) is correctly specified.

---

## Synthesis

The design's architecture is sound: the merge-at-_build_context pattern, the
gate/executor/MCP-client unchanged invariant, and the fail-closed
dependency/collision posture are all well-conceived. The constitutional spine
(no LLM judgment, no new LLMPurpose, gate as sole chokepoint) is correctly
inscribed.

The single blocking finding (R1) is a **documentation-order sequencing bug**:
the ADR's step ordering puts code import before collision-check, while the
plan's atomic ordering correctly puts collision-check first. The ADR is the
binding contract — it must match the plan's safe ordering. This is a plan-stage
fix with zero implementation cost; catch it now, not at impl review.

The six yellow findings cluster around **threat-model honesty** (Y1, Y3, Y5):
the ADR's framing systematically understates the risk delta between "3
known-bounded host closures" and "arbitrary third-party in-process code." Each
individual understatement is small; collectively they present Posture A as a
smaller step from the status quo than it actually is. The architect's Accept
decision should be made with the unvarnished risk picture.

The two remaining yellows (Y2, Y4, Y6) are implementation-adjacent: an ambiguity
in the advisory-cap semantics, an implicit atomic-merge discipline, and an
unstated migration surface. All are cheap to resolve at plan stage.

**Net assessment**: the design is correct but the ADR's threat-model framing
needs tightening. One ADR amendment (R1) + six clarifications before the
architect's D4 posture Accept.

---

# P3.5 R0-B cross-family review — Impl Stage

**Reviewed**: `origin/claude/P3.5-impl` @ `7bec33d` (8 atomics, 17 files, +2169
lines). Plan-stage R1 + Y1–Y6 all α-absorbed per `architect-routing-on-plan.md`;
this review verifies absorption fidelity in code + tests. Seven probe areas
checked against source and test artifacts.

## Probe Results

### (1) R1 — Collision-check BEFORE importlib ✓

**Loader** (`loader.py:1-7`): step order explicitly in module docstring:
Discover(1) → Validate(2) → Collision(3) → Non-code(4) → Code(5) → Rev-cap(6) →
Merge(7). The function `_load_plugin` calls `_collision_check` (step 3) before
the deferred `from orchestrator.plugins.code import ...` (step 5). The import of
`code.py` itself is a local import inside the `if manifest.contributions.tool_impls`
block — it never executes for a collision-refused plugin.

**Test** (`test_failure_modes.py:452-487`): `test_collision_refused_plugin_not_imported`
writes a `tools_impl.py` containing `raise RuntimeError('IMPORT GUARD: ...')`,
declares `tool_impls: {read_file: ...}`, and passes `host_local_tool_names=
frozenset({"read_file"})`. The collision check detects `read_file` in
`host_local_tool_names` → plugin refused → module never imported → no
RuntimeError. **The test proves the invariant**: a collision-refused plugin's
code module is never imported.

**ADR-029 D2** (post-absorption): step order in docstring matches plan execution
order. The plan-stage R1 gap (ADR code-import-before-collision-check) is closed.

### (2) tool_impls Shadow Coverage ✓

**Collision check** (`loader.py:166-191`): `_collision_check` checks tool_impl
names against `host_local_tool_names` (the keys of host `local_tools` — actual
implementations, not ToolMeta-only classifications). A plugin declaring
`tool_impls: {read_file: ...}` hits this check → refused.

**Intentional non-check** (`loader.py:167-175`): tool_impl names are NOT checked
against `host_tools` (ToolMeta-only entries from `config/tools.yaml`). This is
the "host pre-classifies" pattern — the operator pre-classifies a plugin tool in
`config/tools.yaml` (like the demo's `word_count` with rev=10), and the plugin
provides the implementation. If the check were against `host_tools`, the demo
couldn't work. The trade-off is explicit in the code comment.

**Test** (`test_failure_modes.py:381-418`): `test_tool_impl_shadow_host_local_tool_refused` —
plugin declares `tool_impls: {read_file: ...}` against host with `read_file` in
`host_local_tool_names` → refused, `read_file` not in `result.local_tools`. **The
shadow-bypass R0-A Y1 concern is closed**: a plugin cannot shadow a host builtin
implementation.

**Demo pattern** (`plugins/demo/plugin.yaml`, `config/tools.yaml`): the demo's
`word_count` is NOT declared in `contributions.tools`; it's only in
`contributions.tool_impls`. The host `config/tools.yaml` pre-classifies it with
rev=10. The demo's own `plugins/demo/tools.yaml` is parsed but its content is
filtered out (not in `declared_tools`) — the host classification is the sole
authoritative ToolMeta. This is the intended "host pre-classifies" flow.

### (3) Posture A Exposure Honesty ✓

**`code.py` docstring** (lines 1-24): all three exposures are explicitly
inscribed with architect-Accepted language:

- **L1**: "No technical isolation + zero credential/env protection.
  In-process plugin code runs with full host privilege (FS, network, os.environ
  — every API key/secret). ADR-027 D4 credential-indirection + scoped-env are
  MCP-subprocess-only; they provide ZERO protection here."
- **L1b**: "Import-time code is ungated by construction. importlib exec_module()
  runs the module top-level at boot before any gate/room/turn exists. Curation
  is the only control; step-ordering ensures this runs only after the
  validate+collision gauntlet, never before a refusal."
- **L2**: "Posture A VOIDS ADR-028 D5's absolute per-turn liveness bound for
  the plugin-local path — server-wide DoS blast radius. One buggy curated tool
  blocks the max_workers=1 writer for every room, indefinitely, with no cap and
  no kill (in-process is unkillable)."

The `_import_module_from_file` function (`code.py:49-56`) uses
`spec_from_file_location` + `module_from_spec` + `exec_module` — the module runs
in-process. No sandbox, no timeout, no env scoping. The comment on L1 is not
hyperbole: `import os; os.environ` in a plugin tool reads every host secret.
**No pretend isolation.** The gap between Posture A's "fail-closed-against-
breakage" (HR#5 — import error/raise → refused/TOOL_FAILED) and "contains
malicious code" (which A does NOT do) is explicitly stated in the docstring's
first sentence: "Fail-closed-against-breakage IS fully delivered."

### (4) Atomic Merge — Zero Trace ✓

**`_load_plugin`** (`loader.py:260-355`): returns `PluginLoadResult | None`.
`None` on any failure — collision, non-code load error, code load error, or
reversibility cap. The intermediate `PluginLoadResult` is the per-plugin
accumulator; it's only merged into the host registries in `load_plugins` after
`_load_plugin` returns a non-None result.

**`load_plugins`** (`loader.py:374-410`): the `for candidate in candidates` loop
calls `_load_plugin`, checks `if result is None: continue`, and only updates
`seen_*` sets + `merged.*` dicts on success. The `seen_*` sets are updated
atomically AFTER `_load_plugin` succeeds — not incrementally during loading. A
cross-plugin collision is detected by the next `_collision_check` call.

**`_build_context`** (`app.py:158-179`): the merge uses `{**dict1, **dict2}`
pattern which creates a new dict — the host registries are never mutated in-place
by a partially-loaded plugin. Plugin contributions that passed all stages are
merged; refused/partial plugins leave no trace.

**Test** (`test_merge.py:117-167`): `test_partial_plugin_leaves_no_trace` — a
plugin with valid manifest + agent + tool classification + broken code import →
`PluginCodeLoadError` → returned `None` → `assert "bad_role" not in result.agents`
+ `assert "bad_tool" not in result.tools` + `assert "bad_tool" not in result.
local_tools`. **Zero trace.** Test `test_valid_sibling_survives_failing_plugin`
confirms per-plugin isolation.

### (5) Fail-Closed Loading ✓

Every failure mode from HR#5 has a test in `test_failure_modes.py`:

| Failure mode | Test | Mechanism |
|---|---|---|
| Extra manifest field | `test_manifest_extra_field_rejected` | Pydantic `extra="forbid"` |
| Frozen mutation | `test_manifest_frozen` | Pydantic frozen |
| Bad YAML | `test_bad_yaml_manifest_refused` | `yaml.safe_load` exception |
| Non-mapping YAML | `test_manifest_not_mapping_refused` | `isinstance(raw, dict)` |
| Unknown schema_version | `test_unknown_schema_version_refused` | `field_validator("schema_version")` |
| Manifest id ≠ dir name | Implicit in `_discover_and_validate` | `manifest.id != plugin_id` check |
| Unmet model_id | `test_unmet_model_id_dependency_refused` | `models.get(mid) is None` |
| Unmet room_type | `test_unmet_room_type_dependency_refused` | `rt not in host_room_types` |
| min_host_contract too high | `test_min_host_contract_too_high_refused` | `> host_contract_version` |
| Role collision | `test_role_collision_with_host_refused` | `_collision_check` host check |
| Tool collision | `test_tool_collision_with_host_refused` | `_collision_check` host check |
| Cross-plugin skill collision | `test_cross_plugin_skill_collision_refused` | `_collision_check` cross-plugin |
| MCP server collision | `test_mcp_server_collision_with_host_refused` | `_collision_check` host check |
| Shadow host local_tool | `test_tool_impl_shadow_host_local_tool_refused` | `_collision_check` host_local_tool_names |
| Broken import | `test_broken_module_import_refused` | `PluginCodeLoadError` catch |
| Missing callable | `test_missing_callable_in_module_refused` | `getattr(module, name)` → None |

All refused plugins leave host registries unmodified (verified per-test via
`assert result.<field> == {}`). No case silently half-registers.

### (6) Reversibility Cap ✓

**`_apply_reversibility_cap`** (`loader.py:229-248`):
- Host classification present → `min(plugin_value, host_value)` — plugin can
  only lower, never raise (ADR-027 HR#2 analog).
- No host classification → default 0 → HARD_CONFIRM.

**Tests** (`test_loader.py:266-326`):
- `test_unclassified_plugin_tool_defaults_hard_confirm`: plugin tool with no
  host classification → reversibility 0 → `decide_tier` returns HARD_CONFIRM.
- `test_reversibility_cap_new_tool_defaults_zero`: plugin's `tools.yaml` claims
  rev=10, no host classification → capped to 0.
- `test_host_preclassified_tool_impl_gates_auto`: host pre-classifies tool with
  rev=10, plugin provides only impl (no `contributions.tools`) → combined
  registry shows rev=10 → `decide_tier` returns AUTO_EXECUTE. **The demo's
  word_count flow is tested.**

### (7) Constitution — No Gate/Executor/LLM Decision Symbols ✓

**`test_constitution.py`** (4 assertions, 150 lines):
- **p1**: AST scan forbids `decide_tier`/`emit_gate_decision`/`score`/`gate`(Name)/
  `select_model_and_provider` in `plugins/` — zero violations.
- **p2**: AST scan forbids `orchestrator.llm.providers.*` imports in `plugins/` —
  zero violations.
- **p3**: Frozen `LLMPurpose` set unchanged — no new purpose.
- **p4**: Grep confirms `select_model_and_provider` absent from `plugins/`;
  non-vacuous assertion confirms the symbol IS in `llm/router.py`.

**Imports verified**: `loader.py` imports `ToolMeta` from `orchestrator.autonomy.
scoring` — this is a Pydantic data model, not a decision function. `code.py`
imports `LocalToolFn` from `orchestrator.tools.executor` — a type alias, not the
executor function. Neither triggers the constitution test's forbidden-symbol set.
The `plugins/` package makes zero autonomy/routing/LLM decisions.

## Additional Checks

**Import mechanism** (`code.py:49-56`): `spec_from_file_location` +
`module_from_spec` + `exec_module` — the module is NOT registered in
`sys.modules` by `module_from_spec` (standard importlib behavior for
non-import-path modules). Each plugin gets a unique module name
(`orchestrator_plugin_{plugin_id}_{module_name}`) ensuring no cross-plugin
module-name collision. The plugin's own imports (`import os`, etc.) DO register
in `sys.modules` — standard Python, covered by L1.

**Manifest id ↔ directory name**: `_discover_and_validate` checks
`manifest.id != plugin_id` → refused. Prevents a plugin from claiming a
different identity than its directory.

**Absent plugins/ dir**: `load_plugins` returns empty `PluginLoadResult()` —
clean no-op boot.

**Demo plugin five-surface exercise**: roles (`demo_facilitator`) + skills
(`demo-research`) + MCP server (`demo_filesystem`) + tool classification
(`word_count` via host `config/tools.yaml`) + executable code (`word_count`
via `tools_impl.py`). The demo `tools_impl.py` is a pure, no-I/O, deterministic
function — exactly as specified.

## Synthesis

The implementation is a **faithful, disciplined execution** of the absorbed plan.
Every plan-stage concern (R1 + Y1–Y6) is verifiably addressed in code + tests:

| Plan-stage concern | Disposition |
|---|---|
| R1 (ADR ordering: code before collision) | Code step order is collision-first; test `test_collision_refused_plugin_not_imported` proves it |
| Y1 (src/ analogy) | Retired from ADR; code uses operator-curation framing |
| Y2 (default-0 ambiguity) | Resolved: unclassified → 0 → HARD_CONFIRM; demo uses host pre-classification |
| Y3 (L2 understatement) | `code.py` docstring: "server-wide DoS blast radius … no cap and no kill" |
| Y4 (atomic merge implicit) | Explicit per-plugin intermediate; test `test_partial_plugin_leaves_no_trace` |
| Y5 (credential/env scope) | `code.py` docstring: "ADR-027 D4 … provide ZERO protection here" |
| Y6 (A→B migration) | ADR-029 Reversibility table itemizes migration surface |

The 8-atom commit structure (schema → discover → collision → code → wire →
constitution → demo → tests) follows the plan's execution order exactly. The
empty-gate-diff + empty-executor-diff invariant holds: the only change to
`app.py` is one aggregation pass in `_build_context`; `process_tool_calls`,
`_execute_local_call`, and the MCP client are untouched.

**Verdict: clean.** Zero findings. The cross-family lens confirms what the
plan-stage absorption promised: secure-by-construction loading order, honest
Posture A exposure, atomic merge, comprehensive fail-closed coverage. The
implementation is ready for architect Accept + merge.
