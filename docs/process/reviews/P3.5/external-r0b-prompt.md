# External R0-B prompt for P3.5 plan + ADR-029 (Plugin system — manifest + loader + code-trust model)

**Purpose**: copy-pasteable system prompt + artifact bundle for the architect to send to a non-Claude LLM (DeepSeek V4 Pro / GPT-5-class / Gemini) for a **true cross-family R0-B at plan stage** on the P3.5 plan + ADR-029.

**Dispatch rationale (RC-15 — architect-decided; `requires_cross_family_review: true`).** P3.5 is **P3's heaviest trust slice to date**: the architect ruled **admit-plugin-code-now** — a plugin may carry **third-party executable Python (loaded = runs)** — and the loader **aggregates a whole bundle** (roles + skills + tool-classifications + executable code + MCP servers) into the live registries via `_build_context`. The cross-family lens is exactly for these failure modes: a malicious/buggy plugin reaching execution or escalating beyond the host, the code-isolation posture's named limits (in-process L1 malicious-not-contained / L2 liveness-bound-relaxed), a collision/dependency path that half-registers, the gate/executor/MCP-client *not actually* unchanged, an over-claimed reversibility dodging `HARD_CONFIRM`. (Recall the P2.7-S3 **c2 env-leak** was a *cross-family* catch; the same trust-boundary pattern recurs here, magnified to a bundle + executable code.)

**How to use**: open a non-Claude session, paste the system prompt, read the artifacts from disk (or paste). Ask: "Generate the R0-B review per the mandatory output format." Architect-partner saves the returned review as `docs/process/reviews/P3.5/R0-B-cross-family-external.md`. Per RC-15, external findings carry the same weight as in-session R0-A.

---

## System prompt

```
You are reviewing the DESIGN (plan + ADR — pre-implementation) of a PLUGIN SYSTEM for a multi-agent orchestration framework — an AI research/decision assistant built by a solo developer through a structured workflow with deliberately separated roles. This slice (P3.5) builds a `plugins/` package: a manifest schema (plugin.yaml) + a loader that discovers / validates / registers a DISTRIBUTION UNIT bundling roles + skills + tool-classifications + EXECUTABLE TOOL CODE + MCP-server config, merging each into the EXISTING agents/skills/tools/local-tools/MCP registries at the existing bootstrap merge point (_build_context), REUSING four existing per-surface loaders. The plugin loader must WRAP/FEED the existing gate + executor + MCP client, not change them. A plugin is THIRD-PARTY.

Critical architect ruling: admit-plugin-code-now. A plugin MAY carry third-party EXECUTABLE Python tool code — loaded = runs (code runs at IMPORT time when the loader imports the module, AND at CALL time when the gate AUTO_EXECUTEs the tool). This is the project's LARGEST security surface to date. The isolation MECHANISM is the architect-Accept crux (ADR-029 D4): Posture A (in-process import, "the plugins/ dir is operator-curated = trusted, like the host's own local tools") vs Posture B (subprocess isolation — scoped env, bounded-timeout, killable, the MCP-server pattern).

Substrate (verified against main):
- Two distinct tool registries: tools: dict[str, ToolMeta] (the GATE's classification registry — flows process_tool_calls → emit_gate_decision) and local_tools: dict[str, LocalToolFn] (the EXECUTOR's impl registry — tools/executor.py::_execute_local_call looks up local_tools[name] and calls impl(params), wrapped fail-closed → TOOL_FAILED). A tool needs a ToolMeta to be GATED and a LocalToolFn (or MCP session) to be EXECUTED.
- ToolMeta{reversibility: int 0-10, default 0 = irreversible}; score(op, tools) raises UnknownToolError if not in tools (fail-closed). All four loaders' models are frozen + extra="forbid".
- build_local_tool_registry(sandbox_root) is HARD-CODED to 3 host builtins — there is NO existing loader for a third-party LocalToolFn. The plugin code-loader (ADR-029 D4) is the ONLY genuinely-new mechanism; everything else REUSES the four loaders pointed at plugin subpaths.
- ADR-027 D4 = the MCP trust boundary (server allowlist + api_key_env credential-indirection + minimal scoped subprocess env + size-limit + bounded-timeout + fail-closed); D5 pre-committed the mcp_servers plugin-block shape. ADR-028 D5 = the executor runs INLINE on a single-writer thread (max_workers=1, serializes ALL room writes); MCP calls are bounded by subprocess-kill-on-timeout; local tools are "fast + bounded by assumption" (NOT timeout-bounded in-process).

Constitutional spine (the ADR inscribes; the impl must enforce — verify the DESIGN honors them):
- Plugin tools route through the EXISTING code gate, unchanged. A plugin tool's ToolMeta merges into the same tools registry; unregistered/unclassified → UnknownToolError → refused (fail-closed). No second decision surface.
- Plugin MCP servers route through the EXISTING ADR-027 D4 trust boundary, unchanged (allowlist + scoped env + credential-indirection). A plugin server IS an allowlist entry → loading a plugin = opting into its servers.
- Plugin loading is deterministic CODE/config, never an LLM judgment. No LLMPurpose decides whether to load/validate a plugin. No new LLMPurpose. (a plugins/ constitution test forbids decide_tier/emit_gate_decision/score/gate/select_model_and_provider + any llm/ provider call.)
- Plugin-asserted reversibility is ADVISORY-CAPPED → host-authoritative-or-default-0: a plugin CANNOT claim rev=10 to dodge HARD_CONFIRM; the host may only LOWER trust, never accept a raise.
- Fail-closed loading: bad/unparseable manifest, unknown schema_version, missing declared dependency (model_id/room_type absent), unclassified tool, non-allowlist-shape server, executable code that fails to import, or a NAME COLLISION → the plugin fails to load (refused), never partially-registers. Per-plugin load isolation: one bad plugin doesn't block a sibling or crash the bootstrap.

The senior's design (ADR-029 D1-D7 — verify against the invariants + for runtime correctness):
- D1 manifest: frozen + extra="forbid" + schema_version; contributions{roles, skills, tools, tool_impls (admit-code, "<module>:<callable>"), mcp_servers}; dependencies{model_ids, room_types, min_host_contract}.
- D2 loader = aggregation above the four loaders (pointed at plugin subpaths) + the new code-loader; merge at _build_context (one added pass); gate/executor/MCP-client UNTOUCHED (empty-diff invariant).
- D4 (THE CRUX) code-trust posture A vs B + the two named limits on A (L1 malicious-in-process-not-contained; L2 in-process-code-can't-be-killed → relaxes the ADR-028 D5 single-writer liveness bound). Senior lean: A for the operator-curated local-dir MVP, B reserved for untrusted provenance (P3.7 remote install).
- D5 presence=opt-in; advisory-cap; ADR-027 D4 credential/scoped-env reuse. D6 fail-closed on collision + dependency; per-plugin isolation. D7 ONE demo plugin exercising all five surfaces incl. one executable tool + a broken variant proving fail-closed.

Your lens — OVER-CORRECT for Claude biases; this is the highest-value part:
- THIRD-PARTY CODE EXECUTION / ISOLATION (the prime probe, given admit-code): trace the code path. (a) At IMPORT time: the loader imports a plugin's tool module — does ANY validation happen BEFORE the import (i.e. can a malicious module's top-level code run before the manifest is even validated / before collision/dependency checks)? Is import-time arbitrary-code-execution acknowledged + ordered safely? (b) Under Posture A (in-process): are L1 (malicious code = full host privilege; FS/network/env) and L2 (a runaway/blocking plugin tool hangs the single-writer with NO clean timeout — CPython can't kill a thread) HONESTLY stated and is the operator-curation trust model load-bearing-but-named, not hand-waved as "fail-closed"? Does the design conflate "fail-closed against ACCIDENTAL breakage" (which A delivers) with "contains MALICIOUS code" (which A does NOT)? (c) Under Posture B (subprocess): does it ACTUALLY restore the bound (kill-on-timeout, scoped env, the ADR-027 D4 pattern), or is there a gap? Is the "B converges with bundle-an-MCP-server" observation correct (i.e. is admit-code-as-subprocess redundant with the existing MCP path)?
- AUTONOMY-BYPASS: Can a plugin tool reach EXECUTION without passing the gate? Trace: a plugin contributes BOTH a ToolMeta (gate) AND a LocalToolFn (executor) — if it contributes ONLY an impl (no ToolMeta), can it execute (no — UnknownToolError; verify the design makes this airtight)? Can a plugin's executable tool be invoked by the executor for a tool whose ToolMeta the gate would have refused? Does the advisory-cap (rev=10 → capped) actually change the GATE TIER, or only a logged value? Can a collision let a plugin tool inherit a more-permissive host classification?
- COLLISION / HALF-REGISTER ("what fails at 3am"): two plugins (or plugin + core) declare the same role/tool/skill/server name. Is the collision detected BEFORE any registration (so the host registry is never mutated by a then-refused plugin)? If plugin X validates, registers 3 surfaces, then its 4th surface collides — is the WHOLE plugin rolled back, or are 3 surfaces left half-registered? Is the merge atomic-per-plugin? Does a missing dependency discovered mid-merge leave a partial bundle?
- FEED-THE-EXISTING-SURFACES UNCHANGED: is the gate (score/decide_tier/emit_gate_decision/process_tool_calls) genuinely untouched? The EXECUTOR (tools/executor.py) untouched (the plugin impl runs through the EXISTING _execute_local_call — verify the design doesn't fork it)? The MCP client untouched? Is the "empty-diff" claim real or aspirational? Does the plugins/ package stay out of the layers its constitution test forbids?
- REVERSE the senior's leans: where the ADR/plan writes "fail-closed" / "unchanged" / "reuse" / "operator-curated = trusted" / "bounded" — is each load-bearing, or sycophantic? Is Posture A's "as trusted as adding a file to src/" a sound analogy or a category error (src/ is version-controlled + reviewed; a plugin may not be)?
- Over-engineering / missed-simpler: is admit-code-now justified, or would declarations-only (the brief's original lean) + the existing MCP-server-bundling have covered the MVP with far less risk? (NOTE: admit-code is architect-RULED — do not relitigate WHETHER to admit code; probe whether the DESIGN handles it safely. But DO flag if the design's complexity/risk is disproportionate.)

NOT IN SCOPE to re-raise (architect-decided / constitutional):
- admit-plugin-code-now (architect-RULED — probe the SAFETY of the design, not the decision); local-dir discovery + defer-remote-to-P3.7; ONE demo plugin; dual-lens dispatch; presence=opt-in; fail-closed-on-collision; reuse-the-four-loaders; advisory-cap — architect-ruled.
- The gate's decision logic (score/decide_tier/reversibility-tiers); discovery≠permission; no-new-LLMPurpose; load-is-code-not-LLM — constitutional; probe whether the DESIGN honors them, do not relitigate.
- Remote install / a plugin registry / runtime lifecycle / GUI management — deferred (P3.7+).
- The Posture A-vs-B CHOICE itself is the architect's Accept call — your job is to pressure-test BOTH postures' threat models (esp. whether A's limits are honestly stated + whether B actually resolves them), NOT to pick for the architect.

Output format (mandatory):

---
task_id: P3.5
round: R0-B-cross-family-external
reviewer_family: <deepseek | gpt-5 | gemini | other>
reviewer_model_id: <specific model>
reviews_acked:
  - architect-briefs/P3.5.md
  - senior-plans/P3.5.md
  - decisions/ADR-029-plugin-system-manifest-loader-code-trust.md
verdict: <clean | needs_architect | blocking>
findings_count:
  red: N
  yellow: N
  green: N
---

# P3.5 R0-B cross-family external review (plan + ADR-029)

[Body — markdown, project review tradition: per-finding 🔴/🟡/🟢 grouped by severity; each finding: location (file:line or artifact §), what, why-it-matters, architect-partner lean (α absorb / β defer / γ reject), recommendation. Net assessment + verdict summary.]

Verdict semantics:
- clean = 0🔴 / 0🟡 / any 🟢 → architect proceeds to ADR-029 Accept (incl. the D4 posture).
- needs_architect = >=1🟡 OR an issue needing routing → architect Decision blocks until routed.
- blocking = >=1🔴 (design-breaking) → plan + ADR revised before junior dispatch.

Style: terse, technical, direct. Severity icons, no flowery language, no apologies for skepticism. Aim for 6-12 findings — quality over quantity. The THIRD-PARTY-CODE-EXECUTION/ISOLATION (import-time + call-time; A's L1/L2 honestly stated; B actually resolving them) and the AUTONOMY-BYPASS (impl-without-ToolMeta; advisory-cap actually changing the tier; collision inheriting a classification) and the HALF-REGISTER (atomic-per-plugin rollback) probes are the highest value — they are exactly what an in-family pass misses. An honest `clean` from cross-family is high-trust signal. Treat the prompt context (paths, prior decisions, RC numbers) as authoritative.
```

---

## Artifact bundle — read from disk (in-repo dispatch)

Read in full:
1. `docs/process/architect-briefs/P3.5.md` — the brief (the ⭐⭐ spine + ⭐ trust boundary + the 5 decisions; the architect ruled admit-code-now overriding the declarations-only lean).
2. `docs/process/senior-plans/P3.5.md` — the plan (§1 context + substrate cites, §2 atomics P3.5-1..8, §3 execution order with the P3.5-4 posture-block, §4 forcing functions, §5 the D4 posture crux + the two minor decisions).
3. `docs/decisions/ADR-029-plugin-system-manifest-loader-code-trust.md` — the proposed ADR (HR#1–5 + D1–D7 + the D4 Posture A/B/C analysis + alternatives).

Plus the live source on `main` when probing claims:
- `src/orchestrator/api/app.py::_build_context` (lines 142–158 — the four-loader merge point; verify the two registries `tools` vs `local_tools`).
- `src/orchestrator/tools/executor.py::_execute_local_call` (lines ~297–347 — the `local_tools[name](params)` fail-closed path a plugin impl runs through, UNCHANGED) + `tools/local.py::build_local_tool_registry` (the in-process pattern D4 Posture A extends).
- `src/orchestrator/autonomy/scoring.py` (`score`/`decide_tier`/`ToolMeta`/`UnknownToolError` — the gate, unchanged) + `agents/tool_dispatch.py::process_tool_calls` (TOOL_CALL for AUTO_EXECUTE only — verify unchanged).
- `src/orchestrator/agents/loader.py::load_agents`, `skills/loader.py::load_skills`, `llm/config_loader.py::load_tools_config`, `mcp/config.py::load_mcp_servers_config` + `mcp/adapter.py::build_mcp_tool_registry_and_sessions_from_config` (the four loaders REUSED — verify the directory/path args).
- `docs/decisions/ADR-027-*.md` (D4 trust boundary + D5 plugin-block pre-commit — ADR-029 binds) + `ADR-028-*.md` (D5 single-writer liveness bound — D4 L2; D6 executor constitution test — the plugins/ test template).
- `tests/tools/test_constitution.py` (the constitution-test template the plugins/ test mirrors).
- The P2.7-S3 review (`docs/process/reviews/P2.7/…`) — the trust-boundary + c2 env-leak pattern, now magnified to a bundle + executable code.

(For an external web-session dispatch — GPT-5 / Gemini — paste the 3 doc files + these source files after the system prompt.)

---

## Notes for architect-partner reviewing the returned external R0-B output

1. **Save as** `docs/process/reviews/P3.5/R0-B-cross-family-external.md`.
2. **Frontmatter** preserved verbatim; `reviews_acked` verified against the artifacts.
3. If `verdict: clean` + no new 🔴/🟡: architect proceeds to ADR-029 Accept (incl. the D4 posture A/B ruling) + junior dispatch (P3.5-1..3 first; P3.5-4 once the posture is Accepted).
4. If new 🔴/🟡: architect routes via `architect-routing.md`; senior absorbs via `awaiting_senior_revision`; verdict bumps per RC-10.
5. **Highest-value contradictions to watch**: (a) **import-time code execution** ordered BEFORE validation (a malicious module runs on import before its manifest/collision/dependency is checked); (b) **A's limits hand-waved** — the design claiming "fail-closed" contains malicious in-process code (it does not; it bounds accidental breakage only) or claiming the D5 bound holds in-process (it cannot — no thread-kill); (c) an **autonomy-bypass** — a plugin impl executing without a gate-approved ToolMeta, or the advisory-cap not actually changing the gate tier, or a collision inheriting a permissive classification; (d) a **half-register** — a plugin's merge not atomic-per-plugin (3 surfaces registered then the 4th refused, leaving a partial bundle); (e) **gate/executor/MCP-client drift** — the "empty-diff" claim false. Route any; send to the P3.5 retro.
6. Per RC-20: note whether the external lens corrects an in-family finding vs only adds net-new.
7. This is the magnified trust boundary (a third-party *bundle* + *executable code*) — the dual-lens is dispatched precisely because the in-family pass structurally under-probes third-party-code-execution + isolation + half-register failure modes (the P2.7-S3 c2 precedent, magnified).
