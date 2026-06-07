---
task_id: P4.7-BE
review_type: senior-plan-vs-impl
reviewer: senior planner
date: "2026-06-07"
plan_ref: docs/process/senior-plans/P4.7-BE.md
impl_commits: [b750d7b, c559d97, 61540fc, ad59800, e2d94b6]
verdict: clean
findings_count: { red: 0, yellow: 0, green: 3 }
gates:
  ruff: pass
  mypy: "pass (Success: no issues found in 280 source files)"
  pytest: "pass (2283 passed, 2 pre-existing warnings, 314s)"
---

# Senior plan-vs-impl — P4.7-BE

**Lens.** Plan-vs-impl is the *plan-vs-deliverable* surface: does the impl
honour not just the acceptance criteria (which R0-A/R0-B also see) but the
plan-implied invariants only the plan's author can detect drift on
(boot-only spine, fail-closed write guard, seam granularity, the
architect-ratified Y1=(a) / G1 / G2 / G3 absorptions)? Reviewed against
`senior-plans/P4.7-BE.md` rev2 and impl commits T1–T5.

**Verdict: clean (0🔴 / 0🟡 / 3🟢).** Every atomic satisfies its What /
Where / Acceptance and preserves the plan's invariants. The three 🟢 are
benign realizations where the impl is *stricter or more complete* than the
plan prose — none requires action; recorded for the audit trail.

---

## Per-atomic verification

### T1 — `write_plugin_registry` (fail-closed atomic writer) — ✅ faithful
`provenance.py:369-421`. Serializes `plugins:`-list YAML, **round-trip-
validates through `load_plugin_registry` before persisting** (the no-refuse-
all guard, DP3b), **atomic** temp-in-same-dir + `os.replace`, first-write
authors the file (`parent.mkdir(parents=True, exist_ok=True)`), empty-`{}`
permitted. The round-trip raises `(ConfigError, yaml.YAMLError)` ⇒ caught for
temp cleanup ⇒ **re-raised**, leaving the pre-existing file byte-unchanged
(`os.replace` never reached). G1 absorbed: the docstring + inline comment
cite the boot catch set mirror (`app.py:506`). 7 unit tests
(`tests/plugins/test_write_registry.py`) cover identity-fidelity, refuse-all
rejection + byte-unchanged, atomicity, first-write, empty-registry.

### T2 — `AppContext.config_dir` — ✅ faithful
`app.py:128-132` (field `config_dir: Path = field(default_factory=Path.cwd)`,
default-valued for test back-compat) + `app.py:686` (`_build_context`
populates it from its `config_dir` arg). D-A resolved: `ctx.config_dir /
"plugins.yaml"` is the retained path GET + writes need; not stored is the
registry object / load-report (correctly out of scope per §5-P1). No
existing construction breaks (233 API tests pre-existing, full suite green).

### T3 — five management routes — ✅ faithful (the heart of the dispatch)
`app.py` `_register_routes` + `_derive_provenance_and_kind` helper. Verified
against every dispatch checkpoint:
- **boot-only / zero live mutation** ✅ — all four writes are
  `load_plugin_registry → mutate dict → write_plugin_registry → return
  {"effect":"next_restart"}`. No re-call of `load_plugins`, no
  agents/tools/mcp rebuild. (pm5 asserts running registries unchanged.)
- **not in PUBLIC_PATHS** ✅ — `middleware.py:36` PUBLIC_PATHS is
  `{"/login","/health"}` exact-match; all five `/plugins*` routes are
  protected ⇒ 401 before handler (pm6).
- **principal from `request.state`** ✅ — `_principal = request.state.principal`
  on enable/disable/admit/DELETE, commented ADR-039 D7 server-derived,
  never body. (Seam marker; auth itself is enforced by middleware.)
- **admit writes entry only, no fetch** ✅ — `_admit_plugin` upserts
  `RegistryEntry(...)`; no `fetch_plugin_bundle`; comment cites fetch≠admit
  + ADR-031 D5 gauntlet untouched.
- **seam #2 + admit-finer-seam comments** ✅ — seam #2 on
  enable/disable/DELETE; the finer seam #2-admit on admit (higher-trust
  rationale present).
- **GET on `reader_executor`, no last-load-result column** ✅ —
  `run_in_executor(ctx.reader_executor, _read)`; `_PluginInfo` columns =
  `plugin_id / enabled / version / provenance / provenance_kind / fetched`
  — **no last-load-result** (Y1=(a) deferred). G2 absorbed.
- **G3 provenance fallback** ✅ — `_derive_provenance_and_kind` returns
  `declared-not-yet-on-disk` with kind inferred from the fetched-indicator
  for an entry in neither root (no undefined branch). G3 absorbed.
- enable/disable upsert minimal entry (§5-P3) ✅; DELETE 404 on absent ✅;
  **no new `LLMPurpose`**, autonomy gate / `_execute_local_call` untouched ✅
  (verified `git diff 31943a5..e2d94b6`).

### T4 — acceptance tests — ✅ faithful
`tests/api/test_plugins_mgmt.py` (17 tests). Covers happy paths (admit→GET,
enable/disable, DELETE, first-write-authors), boot-only (pm5), unauth→401 on
all five (pm6), refuse-all-rejected + file byte-unchanged (pm7), forge
extra-field→422 + admit-no-digest→422 (pm8/pm8b), G3 fallback both kinds
(pm9/pm10), provenance from roots (pm11/pm12), DELETE-absent→404. Maps to
every T4 acceptance bullet.

### T5 — amendments-at-impl (no new ADR) — ✅ faithful
ADR-038 D5 (L103 column-note + L112 P4.7-BE annotation block + L127 residual
set), ADR-039 D5/D9, ADR-031 D5 — each dated/attributed, citing P4.7-BE.
**The Y1=(a) last-load-result deferral is inscribed in all three places**
(GET column note, annotation block, residual set) with the realized-vs-pinned
reason (avoid touching byte-frozen `load_plugins` for one GUI column) — the
ADR stays honest that 4-columns-+-fetched-indicator shipped, not the pinned
five. Full residual set present: RB-AUTHZ, RB-ADMIT, boot-only/no-live,
last-load-result-deferred, E3-deferred, rate-limiting, admit-author-only→
refused-at-boot-until-fetched.

---

## 🟢 Observations (benign — no action)

- **G-1 — admit-no-digest rejected at the Pydantic schema (422), not (only)
  the writer round-trip the plan prose named.** Plan §2-T3 acceptance said
  "admit with no digest → rejected (the writer round-trip enforces the
  pairing)"; impl makes `digest` a *required* `_AdmitRequest` field ⇒ 422 at
  request validation, with the writer round-trip remaining the backstop for
  any other path. Stricter/earlier + fail-closed; test pm8b documents the
  shift explicitly. Outcome (rejected) satisfied.
- **G-2 — seam #2 comment also planted on DELETE.** Plan named enable/disable
  for seam #2 + admit for the finer seam. DELETE is likewise a boot-only
  authenticated write actuator; the extra seam comment is consistent and
  more complete, not drift. Acceptance ("seam #2 + admit-finer-seam present")
  satisfied.
- **G-3 — writer's cleanup handler catches `BaseException` then re-raises.**
  Plan named the `(ConfigError, yaml.YAMLError)` catch set for the round-trip
  guard. The impl's broad `except BaseException` is *cleanup-only* (unlink
  temp, close fd) and re-raises everything, so the specific guard exceptions
  still propagate and the existing file stays untouched. Robust to interrupt;
  faithful to intent.

---

## Process note (surfaced, not a finding)

State file `.workflow/P4.7-BE.yaml` reads `awaiting_junior_impl` while
impl T1–T5 are committed and this plan-vs-impl ran on architect dispatch —
i.e. the state lagged the expected `awaiting_senior_plan_vs_impl`. Per the
state-machine self-check I did **not** auto-fix it; surfaced to architect.
No stray junior state-advance commit on the impl branch (T1–T5 are
code/doc/test only).

## Expected next transition
Per ADR-008 Amendment 1 (W-005, Route B): on landing this clean
plan-vs-impl, state advances to `awaiting_R0_A` (never short-circuits to
`awaiting_architect_decision`). R0-A.md / R0-B.md already exist on this
branch (parallel impl-stage dispatch); architect routes from the three
review surfaces.
