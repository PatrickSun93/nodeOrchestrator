---
task_id: P4.7-BE
round: R0-A
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 2
---

# P4.7-BE R0-A on impl (architect-partner, cycle 1)

| | |
|---|---|
| Round | R0-A **on impl** (real code, commits T1–T5) |
| Reviewer | A (architect-partner Claude session) |
| Lens | Two-lens, per brief DP5 — **A** = management-endpoint admission/authz trust boundary; **B** = boot-only/spine no-regression. Plus: does the impl **honor** the plan-stage routing (Y1→(a), G1/G2/G3→α absorb, plan rev2 `421f4f2`)? |
| Inputs verified | impl @ `e2d94b6` (`b750d7b`..`e2d94b6`), claim-checked vs live code: `api/{app.py, auth/middleware.py}`, `plugins/{provenance.py, fetch.py, loader.py}`, `tests/{plugins/test_write_registry.py, api/test_plugins_mgmt.py}`, ADR-038/039/031 T5 amendments. Self-ran canonical gates. |
| Verdict | **clean** — both lenses hold on the real code; every plan-stage routing is faithfully realized; the architect-ratified Y1=(a) deferral is honestly inscribed. No 🔴, no 🟡. Two 🟢 impl-absorb doc/quality nits, neither needing a decision. Route nothing. |

## TL;DR

The slice does exactly what the ratified contract pinned: five boot-only management routes that edit `config/plugins.yaml` and signal `{"effect":"next_restart"}`, behind the fail-closed auth boundary, with a round-trip-guarded atomic writer that provably cannot author a refuse-all registry. The load-bearing new surface (`write_plugin_registry`) and the trust boundary (admit = author-entry-only; no fetch) are verified end-to-end against the byte-frozen spine (`load_plugins`/`fetch.py`/the gate). The plan-stage Y1 (`last-load result` GET column vs the frozen spine) was the architect's call at plan time, routed to **(a) defer**; T5 inscribes that deferral truthfully across three ADRs.

## Lens A — admission / authz trust boundary (real code)

| Axis | Question | Evidence | Holds |
|---|---|---|---|
| A1 | Can `admit` introduce code / skip the digest-before-extract gauntlet? | `_admit_plugin` (`app.py:1246-1282`) writes a `RegistryEntry` only — **no `fetch_plugin_bundle` call** (comment `:1250-1257`). The gauntlet (`fetch.py` `fetch_plugin_bundle`: https-only → download → **digest-before-extract** → traversal-guard → atomic rename) is **byte-frozen** (not in the diff). A bundle reaches `fetched_plugins_dir` *only* via that gauntlet; the loader independently **requires activation** for `provenance=="fetched"` (`loader.py:400-413`, fail-closed if absent, ADR-031 D4). admit-only with no on-disk bytes → GET `declared-not-yet-on-disk` → **refused at next boot** until a separate fetch runs. | ✓ |
| A2 | Fail-closed on the whole surface? | `PUBLIC_PATHS = {/login, /health}` (`middleware.py`); the five routes are **absent** → `AuthMiddleware` returns **401 before any handler** (protected-by-default). `pm6` parametrizes all five (GET + 4 writes) × unauth → 401. Principal is read from `request.state.principal` (server-derived) on every write handler (`app.py:1191/1220/1258/1287`), **never** from the body. | ✓ |
| A3 | Can a write produce a refuse-all `config/plugins.yaml` (self-inflicted brownout)? | `write_plugin_registry` (`provenance.py:371-421`): serialize → temp-in-same-dir → **round-trip `load_plugin_registry(tmp_path)`** → `os.replace`. Any parse failure raises; `except BaseException` unlinks the temp and re-raises (existing file byte-unchanged). The round-trip is a **superset** of the boot refuse-all catch set `(ConfigError, yaml.YAMLError)`, so a persisted file provably cannot trip `REGISTRY_REFUSE_ALL`. Atomic; no torn write. The 4 writes all run on `writer_executor` (max_workers=1, `app.py:1215/1244/1282/1301`) → read-modify-write is serialized, no lost update. `pm7` + `wpr4`/`wpr5` cover it. (Plan-stage G1 absorbed ✓.) | ✓ |
| A4 | Can a write forge provenance / a shape↔root mismatch? | `RegistryEntry` has **no** `provenance`/`posture` field; `load_plugin_registry` rejects unknown keys (`provenance.py:283-288`). GET derives provenance **read-only by filesystem root** (`_derive_provenance_and_kind`, `app.py:727-747`), never from the registry. admit body is `{source_url, digest, version}` with `extra="forbid"` (`pm8`); enable/disable carry **no body** at all → structurally cannot author a fetched-shape entry. The loader's shape-coherence guard (`loader.py:369-379`) refuses a fetched-shape entry bound to an operator-placed plugin → **fail-closed, not forge**. | ✓ |

`plugin_id` is a URL path segment used only as a registry **dict key** + a benign `.exists()` provenance-label check; the write target is the fixed `config_dir/plugins.yaml` — no path-traversal-write surface. enable/disable preserve `existing` fetched fields (or write none) — an `enable` on an id that is actually fetched yields a no-`source_url` entry → that one plugin is refused at boot (activation guard), never silently activated.

## Lens B — boot-only / spine no-regression (real code)

- **B1 boot-only** — all four writes mutate `config/plugins.yaml` + return `{"effect":"next_restart"}`; **zero** live `AppContext` mutation (no ctx-registry assignment anywhere in the handlers). `pm5` asserts `ctx.available_agents`/`ctx.tools` unchanged after a write. No runtime-store, no hot-reload. ✓
- **B2 `load_plugin_registry` byte-frozen** — T1 diff is purely additive (`import os, tempfile` + `write_plugin_registry` appended after the loader; `@@ -364,3 +366,56`). The validator bytes are untouched. ✓
- **B3 write-path round-trips the same validator** — `write_plugin_registry` calls `load_plugin_registry(tmp_path)`. ✓
- **B4 no new `LLMPurpose`, gate untouched** — grep across the diff: zero `LLMPurpose`; the autonomy gate / `_execute_local_call` are not in the diff. Admission stays a non-gated config op. ✓
- **B5 existing routes + middleware + seam #1** — T2 (+6) and T3 (+220) are **0-deletion** additions to `app.py`; login/logout/rooms/intent/confirm/stream and `auth/middleware.py` are byte-frozen. ✓
- **B6 `_execute_local_call` / gate** — not in the changed-file set (only `app.py`, `provenance.py`, tests, ADRs). ✓
- **B7 `config_dir` additive** — `config_dir: Path = field(default_factory=Path.cwd)` (`app.py:132`); existing `AppContext` constructions don't break (mypy clean over 280 files; full suite green; the test `_make_ctx` constructs without the prior fields). ✓

Plan-stage **G2** (run GET's `load_plugin_registry` on `reader_executor`) absorbed — GET dispatches `_read` to `ctx.reader_executor` (`app.py:1186`). Plan-stage **G3** (no-dir provenance fallback) absorbed — `_derive_provenance_and_kind` returns `declared-not-yet-on-disk` + a kind inferred from the fetched-indicator (`pm9`/`pm10`). The three dispatch-flagged checks (admit-author-only, admit-finer-seam, no runtime-store) all hold on the real code (seam #2 on enable/disable/DELETE; the finer `seam #2-admit` on admit, `app.py:1250-1252`).

## Y1=(a) — realized-vs-pinned honesty (architect-ratified)

At plan stage I flagged Y1 (`needs_architect`): ADR-038 D5 pinned GET to return `last-load result`, but there is no backing state — `PluginLoadResult` carries only merged contributions and boot outcomes are logged, never retained — so honoring it would mean modifying the exact `load_plugins` spine Lens B certifies frozen. The architect routed **(a) defer** (plan rev2 `421f4f2`). The impl honors it: GET returns `plugin_id / enabled / version / provenance(derived) / provenance_kind / fetched`, and **T5 inscribes the deferral** as a named residual in ADR-038 D5 (table note + annotation block + residual set), with mirroring annotations in ADR-039 D5/D9 and ADR-031 D5. This is inscribe-don't-soften done correctly: the ADR now states truthfully what is realized vs deferred, and `load_plugins` stays byte-frozen. ✓

## 🟢 Green nits (impl-absorb; no architect decision)

- **G1 (doc accuracy)** — the refuse-all catch set is at **`app.py:548`**, but `write_plugin_registry`'s comments (`provenance.py:382,408`) and the T5 ADR-038 D5 annotation cite **`app.py:506`** (accurate when T1 was authored; T2/T3 inserted ~42 lines above it). Semantics are correct — the durable anchor is the named set `(ConfigError, yaml.YAMLError)` — only the line number drifted. Fix the number or drop it (line refs inherently drift).
- **G2 (defense-in-depth surfacing)** — `_AdmitRequest.source_url/digest` are typed `str` (Pydantic allows `""`). An empty-string admit is **fail-closed-rejected** by the writer round-trip (`load_plugin_registry` rejects empty `source_url`/`digest`), so no malformed entry can persist — but it surfaces as HTTP **500** rather than a clean **422**. Optional hardening: `min_length=1` on the two fields for a Pydantic-layer 422. Not a security gap; the floor already holds.

## Canonical gates (self-run)

- **ruff** `check src tests` → All checks passed.
- **mypy** → Success: no issues found in 280 source files.
- **pytest** — new-slice 24/24 pass (7 `test_write_registry` + 17 `test_plugins_mgmt`); **full suite exit 0** (two pre-existing, unrelated warnings: starlette/httpx deprecation; a `test_net_trust` DNS-timeout thread warning — neither from this slice).

## Closing

The trust boundary holds on all four Lens-A axes against the real code; the boot-only/spine invariants hold on all seven Lens-B axes; every plan-stage routing (Y1=(a), G1/G2/G3=α) is faithfully realized; the fail-closed config-writer's refuse-all-prevention is verified end-to-end against `_resolve_plugin_registry`/`load_plugins`. Two cosmetic greens, no decision attached. **I route nothing.**
