---
task_id: P4.7-BE
round: R0-A-on-plan
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 3
---

# P4.7-BE R0-A on plan (architect-dispatched pre-impl review)

| Field | Value |
|---|---|
| Round | R0-A-on-plan (architect-dispatched manual, per RC-9) |
| Reviewer | A (architect-partner Claude session) |
| Family | Claude (Opus) — same as senior |
| Cross-family R0-B | not run at plan-stage; mandatory dual-lens (R0-A ∥ R0-B) is the **impl**-stage gate (`requires_cross_family_review: true`; `external-r0b-prompt.md` already authored) |
| Lens | Two-lens, per brief DP5 — **A** = management-endpoint admission/authz trust boundary; **B** = boot-only/spine no-regression. Plus: does the plan **honor** the ratified DPs (scope-A / DP1a / admit-i / DP2 seam+admit-finer / DP3 / DP4 no-new-ADR)? |
| Inputs verified | brief `4bc96bf` + senior plan `470a469`, claim-checked vs live base @ `470a469`: `api/{app.py, auth/middleware.py}`, `plugins/{provenance.py, fetch.py, loader.py}`, `tests/api/conftest.py` |
| Verdict | **needs_architect** — the plan faithfully realizes every *ratified* DP; one genuinely-open decision (the senior's §5-P1, the pinned GET `last-load result` column) needs an architect ruling. No blocking defect. |

## Scope discipline (per dispatch)

I did **not** relitigate the ratified calls (scope-A / DP1(a) / admit=author-entry-only / no-new-ADR / DP2 authenticated⇒allowed). I verified the plan **honors** them against the live base, and I treated the §5 push-backs as findings **only** where a correctness or pinned-contract-fidelity problem exists (P1 does; P2/P3 do not — see below). Route nothing.

## Lens A — admission/authz trust boundary (verified against live base)

| # | Adversary question | Live-base evidence the plan's design holds | Verdict |
|---|---|---|---|
| A1 | Can an endpoint **admit unverified code / skip the digest gauntlet**? | admit is DP1-i **author-entry-only** — T3 explicitly **does not** call `fetch_plugin_bundle`. The gauntlet (`fetch.py:121`, digest-before-extract `:170-181` → extract `:183-187`) is untouched and still mandatory at the separate fetch step. enable/disable carry no `source_url/digest` in their bodies, so they **cannot author a valid fetched entry** (the `(source_url is None) != (digest is None)` pairing rule, `provenance.py:333-339`, is enforced by the writer round-trip). | honors DP3a ✓ |
| A2 | Can an endpoint act **unauthenticated / as a wrong principal**? | New routes are **not** added to `PUBLIC_PATHS` (`middleware.py:36` = `{/login,/health}`), so the fail-closed-by-default gate (`middleware.py:57-70`) returns `401` before the handler. T3 reads `request.state.principal` (server-derived), mirroring the live seam #1 (`app.py:1002`, principal from `request.state`, **never** the body — ADR-039 D7). | honors DP2 / ADR-039 D7 ✓ |
| A3 | Can a write endpoint **land on the public allowlist**? | T3 acceptance + T4 ("unauth → 401 on every write route + GET") assert non-membership; the 5-surface auth-boundary scan (T3 §4 forcing fn) is the guard. | honors fail-closed ✓ |
| A4 | Can a write **produce a refuse-all `config/plugins.yaml`** (self-inflicted outage)? | This is the heart of the slice and the design is **sound end-to-end**: boot refuse-all fires **only** when `_resolve_plugin_registry` catches `(ConfigError, yaml.YAMLError)` from `load_plugin_registry` (`app.py:506-510`) and hands `REGISTRY_REFUSE_ALL` to `load_plugins`, which then returns an empty `PluginLoadResult()` (`loader.py:634-639`). T1's writer **round-trips the serialized bytes back through the same `load_plugin_registry` before persisting and aborts if it raises** — so a persisted file provably cannot trip refuse-all. Atomic temp-in-same-dir → `os.replace` prevents a torn half-file. (One tightening nit → **G1**.) | honors DP3b ✓ |
| A5 | Can the write path **forge provenance / a shape↔root mismatch**? | Provenance is **never** a registry field — `load_plugin_registry` rejects unknown keys incl. `provenance`/`posture` (`provenance.py:281-286`); GET derives provenance **read-only by root dir**. admit writes only `{source_url,digest,version}`; enable/disable write only `enabled`. No body field reaches a provenance/root decision. | honors un-spoofable invariant ✓ |

## Lens B — boot-only / spine no-regression (verified)

- **Boot-only preserved**: T3 does **no** live `AppContext` mutation — no re-call of `load_plugins`, no agents/tools/`mcp_sessions` rebuild; the write edits `config/plugins.yaml` and the response signals `{"effect":"next_restart"}`. No runtime-store, no hot-reload (the ADR-038-deferred surfaces DP1(b) would have reopened). ✓
- **`config_dir` add is genuinely additive (D-A confirmed)**: `AppContext` (`app.py:103-127`) today has **no** `config_dir`; `_plugin_registry` is a local in `_build_context` (`:596`) consumed by `load_plugins` then dropped (`:615-620`), and `sandbox_root = config_dir.parent` (`:580`) is not invertible. T2 adds `config_dir` as a **default-valued** field mirroring the cycle-2 `sandbox_root`/`local_tools` pattern (`:116-127`); `conftest.py:116-129` builds `AppContext` directly and already omits several default-valued fields, so existing test constructions still build, and `_make_test_app(ctx)` (`:1302`) takes the ctx as-is. ✓
- **Validator byte-frozen + write-path round-trips it**: T1 explicitly keeps `load_plugin_registry` out of scope and *uses* it as the round-trip oracle. ✓
- **Gate untouched**: no new `LLMPurpose` (T3 acceptance + `grep LLMPurpose` forcing fn); admission stays a non-gated operator action (ADR-038 DP2c); `_execute_local_call`/gate byte-frozen. ✓
- **Existing routes + middleware + seam #1 no regression**: routes are additive; middleware unchanged; seam #1 (`app.py:997/:1002`) is **mirrored**, not modified. The forge-guard pattern T3 reuses (`model_config = ConfigDict(frozen=True, extra="forbid")`) is live at `app.py:162/:169` (`_CreateRoomBody`/`_LoginRequest`). ✓

**Ratified-DP honor check (the three the dispatch flagged):** admit = (i) writes the entry only, not coupled to fetch — ✓ (T3 "No `fetch_plugin_bundle` call"). DP2 gives admit its **own finer seam** — ✓ (T3 plants a separate `seam #2-admit` comment marking admit as strictly higher-trust than enable/disable toggling). boot-only does **not** smuggle a runtime-store — ✓ (no live mutation; `config_dir` is a path, not a retained mutable registry).

## §5 push-backs I checked

- **P3 (enable/disable on a registry-absent operator-placed plugin)** — concur with the senior's in-plan resolution; **no finding**. An operator-placed plugin loads with no entry (`loader.py:650`, presence=opt-in); authoring a minimal `{plugin_id, enabled}` entry round-trips cleanly (both `source_url`/`digest` absent satisfies the pairing rule). An `enable` that authors `{plugin_id, enabled:true}` for an id that is actually *fetched* yields a no-`source_url`/`digest` entry → that **one** plugin is refused at next boot (fail-closed activation, ADR-031 D4) — **not** refuse-all, **not** admit-unverified. The write path cannot forge a valid fetched entry. Correct.
- **P2 (GET file-vs-running divergence)** — inherent to boot-only; inscribed as a residual (§6) and the response is marked "configured (effect next restart)." No correctness problem; it is **coupled to P1** (reporting running-state would require the retained boot state P1 is about). Folded into Y1.

## Findings

| # | 🚦 | File : line / task | What's wrong | What should be |
|---|----|-------------|--------------|----------------|
| Y1 | 🟡 | senior plan §5-P1 + T3 (`GET /plugins`) vs **ADR-038 D5 L103** | **A pinned GET column is being dropped, and it needs the architect's explicit blessing.** ADR-038 D5 L103 pins GET to return "id, provenance, enabled, version, **last-load result**." There is **no backing state** for the last column: `PluginLoadResult` (`loader.py:61-76`) holds only merged contributions, and boot load outcomes are logged, never structured/retained on `AppContext`. Faithfully reporting it requires a new per-plugin boot load-report threaded out of `load_plugins` and stored on `ctx` — i.e. **modifying the exact spine Lens B is asked to certify byte-frozen.** This is a genuine collision of two pinned things (the D5 GET shape vs the load_plugins freeze), it was **not** part of the ratified DP set, and the plan correctly escalates it rather than silently choosing. The plan's default (defer the column) means the realized GET contract is **incomplete vs the pinned ADR-038 D5**. | **Architect ruling required (I do not route).** Two options the plan lays out: **(a) defer** `last-load result` as a named residual — GET returns id / provenance(derived) / enabled / version / fetched-indicator; `load_plugins` stays byte-frozen (the senior's stated lean; smallest Lens-B surface). **(b) fund** a minimal additive boot load-report (`{plugin_id, provenance, loaded\|refused, reason}` returned from `load_plugins`, stored on `ctx`) — honors D5 verbatim but **widens the Lens-B surface** (touches the frozen spine) and would add a task. **Either way, T5's ADR-038 D5 amendment must record the outcome** — if (a), inscribe the dropped column as a residual so the ADR stays truthful about realized-vs-deferred; if (b), the amendment notes it realized in full. Impl is not otherwise blocked (the senior notes GET works either way; only this one column changes). |
| G1 | 🟢 | T1 (`write_plugin_registry` round-trip guard) | T1 says "abort the write if the round-trip raises **`ConfigError`**," but the boot refuse-all trigger catches **`(ConfigError, yaml.YAMLError)`** (`app.py:506`). In practice `yaml.safe_dump → safe_load` cannot emit a `YAMLError`, so catching `ConfigError` alone is *sufficient today* — but the writer's stated invariant is "round-trip mirrors the boot parse," and an exact mirror is robust to any future serializer change. | Catch the **same** exception set the boot path catches — `except (ConfigError, yaml.YAMLError)` — on the round-trip, so the guard provably mirrors `_resolve_plugin_registry`. Impl-absorb; no architect decision. |
| G2 | 🟢 | T3 (`GET /plugins` read) | The house non-blocking-I/O discipline runs all reads off the event loop onto `ctx.reader_executor` (the existing read routes `app.py:758/769/778/795`; `middleware._resolve_principal` too). T3 does not state that GET's `load_plugin_registry` (sync file read) runs on the reader executor. The file is tiny so the latency is negligible, but the consistency (and growth-safety) argues for matching the discipline. | Run GET's `load_plugin_registry(ctx.config_dir/"plugins.yaml")` on `ctx.reader_executor` like the sibling read routes. Impl-absorb; no architect decision. |
| G3 | 🟢 | T3 (`GET /plugins` provenance derivation) | T3 derives provenance "by which root dir contains the id." For an **admitted-but-not-yet-fetched** entry (the DP1-i residual), the id is in **neither** `plugins/` nor `fetched_plugins/`, so root-based derivation has an undefined branch. The plan separately exposes a "fetched-indicator (has source_url/digest)," so the data exists — but the no-dir provenance fallback isn't spelled out and a naive `if/elif` would mislabel or error. | Spell out the fallback: an entry present in neither root is reported as declared-not-yet-on-disk (provenance inferred from the fetched-indicator: `source_url`+`digest` ⇒ "fetched (pending)"; else "operator-placed (pending)"). Impl-absorb; no architect decision. |

## Bottom line

The plan is **well-targeted and faithful** to the ratified contract: the trust boundary holds on all five Lens-A axes, the boot-only/spine invariants hold on all Lens-B axes, and the three dispatch-flagged checks (admit-author-only, admit-finer-seam, no runtime-store) are honored against the live base. The fail-closed config-writer (T1) is the load-bearing new surface and its refuse-all-prevention argument is **verified end-to-end** against `_resolve_plugin_registry`/`load_plugins`.

The single thing the architect must rule before this is "clean": **Y1 — defer the pinned `last-load result` GET column (residual), or fund the minimal additive boot load-report.** G1–G3 are impl-absorb nits requiring no decision. I route nothing.
